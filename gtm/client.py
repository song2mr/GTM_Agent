"""GTM API v2 클라이언트 래퍼.

리소스 생성 순서: Variable → Trigger → Tag
이름 충돌 시 Create 대신 Update(덮어쓰기) 호출.
"""

from __future__ import annotations

import os
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from gtm.auth import get_credentials
from gtm.models import GTMTag, GTMTrigger, GTMVariable


class GTMClient:
    def __init__(self, account_id: str = "", container_id: str = ""):
        creds = get_credentials()
        self._service = build("tagmanager", "v2", credentials=creds)
        # UI 또는 CLI에서 전달된 값 우선, 없으면 환경변수 폴백 (하위 호환)
        self.account_id = account_id or os.environ.get("GTM_ACCOUNT_ID", "")
        self.container_id = container_id or os.environ.get("GTM_CONTAINER_ID", "")
        # 리소스 목록 캐시 (workspace_id별) — API 호출 수 최소화
        self._variable_cache: dict[str, list[dict]] = {}
        self._trigger_cache: dict[str, list[dict]] = {}
        self._tag_cache: dict[str, list[dict]] = {}

    # ── 경로 헬퍼 ──────────────────────────────────────────────────────────

    def _account_path(self) -> str:
        return f"accounts/{self.account_id}"

    def _container_path(self) -> str:
        return f"accounts/{self.account_id}/containers/{self.container_id}"

    def _workspace_path(self, workspace_id: str) -> str:
        return (
            f"accounts/{self.account_id}/containers/{self.container_id}"
            f"/workspaces/{workspace_id}"
        )

    # ── Workspace ──────────────────────────────────────────────────────────

    def list_workspaces(self) -> list[dict]:
        """컨테이너의 Workspace 목록을 반환합니다."""
        result = (
            self._service.accounts()
            .containers()
            .workspaces()
            .list(parent=self._container_path())
            .execute()
        )
        return result.get("workspace", [])

    def delete_workspace(self, workspace_id: str) -> None:
        """Workspace를 삭제합니다 (기본 Workspace 제외)."""
        self._service.accounts().containers().workspaces().delete(
            path=self._workspace_path(workspace_id)
        ).execute()

    def create_workspace(self, name: str = "gtm-ai-workspace") -> dict:
        """이전 gtm-ai-* Workspace를 정리하고 신규 Workspace를 생성합니다."""
        # 기존 gtm-ai-* Workspace 삭제 (최대 3개까지만 유지하여 Rate Limit 방지)
        try:
            workspaces = self.list_workspaces()
            ai_workspaces = sorted(
                [w for w in workspaces if w.get("name", "").startswith("gtm-ai-")],
                key=lambda w: w.get("workspaceId", "0"),
            )
            # 가장 오래된 것부터 삭제 (최근 2개만 남김)
            for old_ws in ai_workspaces[:-2] if len(ai_workspaces) > 2 else []:
                try:
                    self.delete_workspace(old_ws["workspaceId"])
                    print(f"[GTMClient] 이전 Workspace 정리: {old_ws['name']} (id={old_ws['workspaceId']})")
                except Exception as e:
                    print(f"[GTMClient] Workspace 삭제 실패 (무시): {e}")
        except Exception as e:
            print(f"[GTMClient] Workspace 목록 조회 실패 (무시): {e}")

        body = {"name": name, "description": "Created by GTM AI Agent"}
        result = (
            self._service.accounts()
            .containers()
            .workspaces()
            .create(parent=self._container_path(), body=body)
            .execute()
        )
        return result

    def get_workspace(self, workspace_id: str) -> dict:
        return (
            self._service.accounts()
            .containers()
            .workspaces()
            .get(path=self._workspace_path(workspace_id))
            .execute()
        )

    # ── Container 설정 조회 ────────────────────────────────────────────────

    def list_tags(self, workspace_id: str) -> list[dict]:
        result = (
            self._service.accounts()
            .containers()
            .workspaces()
            .tags()
            .list(parent=self._workspace_path(workspace_id))
            .execute()
        )
        return result.get("tag", [])

    def list_triggers(self, workspace_id: str) -> list[dict]:
        result = (
            self._service.accounts()
            .containers()
            .workspaces()
            .triggers()
            .list(parent=self._workspace_path(workspace_id))
            .execute()
        )
        return result.get("trigger", [])

    def list_variables(self, workspace_id: str) -> list[dict]:
        result = (
            self._service.accounts()
            .containers()
            .workspaces()
            .variables()
            .list(parent=self._workspace_path(workspace_id))
            .execute()
        )
        return result.get("variable", [])

    # ── Variable ──────────────────────────────────────────────────────────

    def create_or_update_variable(
        self, workspace_id: str, variable: GTMVariable
    ) -> dict:
        """Variable을 생성하거나, 같은 이름이 있으면 Update합니다."""
        existing = self._find_variable(workspace_id, variable.name)
        body = variable.to_api_body(self._workspace_path(workspace_id))

        if existing:
            result = (
                self._service.accounts()
                .containers()
                .workspaces()
                .variables()
                .update(path=existing["path"], body=body)
                .execute()
            )
            print(f"[Variable] 업데이트: {variable.name}")
        else:
            result = (
                self._service.accounts()
                .containers()
                .workspaces()
                .variables()
                .create(parent=self._workspace_path(workspace_id), body=body)
                .execute()
            )
            print(f"[Variable] 생성: {variable.name}")

        # 캐시 업데이트 (무효화 대신 결과 추가 → list 중복 호출 방지)
        if workspace_id in self._variable_cache:
            self._variable_cache[workspace_id].append(result)
        return result

    def _find_variable(self, workspace_id: str, name: str) -> dict | None:
        # 캐시 활용으로 list_variables는 workspace당 1회만 호출
        if workspace_id not in self._variable_cache:
            self._variable_cache[workspace_id] = self.list_variables(workspace_id)
        for v in self._variable_cache[workspace_id]:
            if v["name"] == name:
                return v
        return None

    # ── Trigger ───────────────────────────────────────────────────────────

    def create_or_update_trigger(
        self, workspace_id: str, trigger: GTMTrigger
    ) -> dict:
        """Trigger를 생성하거나, 같은 이름이 있으면 Update합니다."""
        existing = self._find_trigger(workspace_id, trigger.name)
        body = trigger.to_api_body(self._workspace_path(workspace_id))

        if existing:
            result = (
                self._service.accounts()
                .containers()
                .workspaces()
                .triggers()
                .update(path=existing["path"], body=body)
                .execute()
            )
            print(f"[Trigger] 업데이트: {trigger.name}")
        else:
            result = (
                self._service.accounts()
                .containers()
                .workspaces()
                .triggers()
                .create(parent=self._workspace_path(workspace_id), body=body)
                .execute()
            )
            print(f"[Trigger] 생성: {trigger.name}")

        if workspace_id in self._trigger_cache:
            self._trigger_cache[workspace_id].append(result)
        return result

    def _find_trigger(self, workspace_id: str, name: str) -> dict | None:
        if workspace_id not in self._trigger_cache:
            self._trigger_cache[workspace_id] = self.list_triggers(workspace_id)
        for t in self._trigger_cache[workspace_id]:
            if t["name"] == name:
                return t
        return None

    # ── Tag ───────────────────────────────────────────────────────────────

    def create_or_update_tag(self, workspace_id: str, tag: GTMTag) -> dict:
        """Tag를 생성하거나, 같은 이름이 있으면 Update합니다."""
        existing = self._find_tag(workspace_id, tag.name)
        body = tag.to_api_body(self._workspace_path(workspace_id))

        if existing:
            result = (
                self._service.accounts()
                .containers()
                .workspaces()
                .tags()
                .update(path=existing["path"], body=body)
                .execute()
            )
            print(f"[Tag] 업데이트: {tag.name}")
        else:
            result = (
                self._service.accounts()
                .containers()
                .workspaces()
                .tags()
                .create(parent=self._workspace_path(workspace_id), body=body)
                .execute()
            )
            print(f"[Tag] 생성: {tag.name}")

        if workspace_id in self._tag_cache:
            self._tag_cache[workspace_id].append(result)
        return result

    def _find_tag(self, workspace_id: str, name: str) -> dict | None:
        if workspace_id not in self._tag_cache:
            self._tag_cache[workspace_id] = self.list_tags(workspace_id)
        for t in self._tag_cache[workspace_id]:
            if t["name"] == name:
                return t
        return None

    def _invalidate_caches(self, workspace_id: str) -> None:
        """workspace의 모든 캐시를 초기화합니다 (강제 새로고침 필요 시 사용)."""
        self._variable_cache.pop(workspace_id, None)
        self._trigger_cache.pop(workspace_id, None)
        self._tag_cache.pop(workspace_id, None)

    # ── Publish ───────────────────────────────────────────────────────────

    def create_version(
        self, workspace_id: str, name: str = "", notes: str = ""
    ) -> dict:
        """Workspace에서 컨테이너 버전을 생성합니다."""
        body: dict[str, Any] = {}
        if name:
            body["name"] = name
        if notes:
            body["notes"] = notes

        result = (
            self._service.accounts()
            .containers()
            .workspaces()
            .create_version(
                path=self._workspace_path(workspace_id), body=body
            )
            .execute()
        )
        return result

    def publish_version(self, version_path: str) -> dict:
        """컨테이너 버전을 Publish합니다."""
        result = (
            self._service.accounts()
            .containers()
            .versions()
            .publish(path=version_path)
            .execute()
        )
        return result
