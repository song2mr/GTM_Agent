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
    def __init__(self):
        creds = get_credentials()
        self._service = build("tagmanager", "v2", credentials=creds)
        self.account_id = os.environ["GTM_ACCOUNT_ID"]
        self.container_id = os.environ["GTM_CONTAINER_ID"]

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

    def create_workspace(self, name: str = "gtm-ai-workspace") -> dict:
        """신규 Workspace를 생성하고 반환합니다."""
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

        return result

    def _find_variable(self, workspace_id: str, name: str) -> dict | None:
        for v in self.list_variables(workspace_id):
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

        return result

    def _find_trigger(self, workspace_id: str, name: str) -> dict | None:
        for t in self.list_triggers(workspace_id):
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

        return result

    def _find_tag(self, workspace_id: str, name: str) -> dict | None:
        for t in self.list_tags(workspace_id):
            if t["name"] == name:
                return t
        return None

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
