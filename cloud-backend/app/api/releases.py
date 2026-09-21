"""版本管理 API（管理员）+ 客户端最新版本查询（需登录）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.deps import get_admin_user, get_current_user, get_db, utcnow
from ..db.models import Release, User
from ..schemas.auth import (
    PublishRequest,
    ReleaseCreateRequest,
    ReleaseOut,
    ReleaseUpdateRequest,
)

admin_router = APIRouter(prefix="/admin/releases", tags=["admin"], dependencies=[Depends(get_admin_user)])
client_router = APIRouter(prefix="/client", tags=["client"])


def _compare_versions(a: str, b: str) -> int:
    """语义化版本比较：a>b 返回 1，a<b 返回 -1，相等返回 0。"""
    def norm(v: str) -> list[int]:
        core = v.split("-")[0]
        return [int(x) for x in core.split(".")]

    na, nb = norm(a), norm(b)
    length = max(len(na), len(nb))
    na += [0] * (length - len(na))
    nb += [0] * (length - len(nb))
    for x, y in zip(na, nb):
        if x != y:
            return 1 if x > y else -1
    return 0


@admin_router.get("", response_model=dict)
def list_releases(db: Session = Depends(get_db)):
    items = db.query(Release).order_by(Release.id.desc()).all()
    return {"items": [ReleaseOut.model_validate(r, from_attributes=True) for r in items]}


@admin_router.post("", response_model=ReleaseOut)
def create_release(body: ReleaseCreateRequest, db: Session = Depends(get_db)):
    if db.query(Release).filter(Release.version == body.version).first():
        raise HTTPException(status_code=400, detail="该版本号已存在")
    release = Release(
        version=body.version,
        notes=body.notes,
        download_url=body.download_url,
        force=body.force,
        published=False,
    )
    db.add(release)
    db.commit()
    db.refresh(release)
    return ReleaseOut.model_validate(release, from_attributes=True)


@admin_router.put("/{release_id}", response_model=ReleaseOut)
def update_release(release_id: int, body: ReleaseUpdateRequest, db: Session = Depends(get_db)):
    release = db.get(Release, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    if body.notes is not None:
        release.notes = body.notes
    if body.download_url is not None:
        release.download_url = body.download_url
    if body.force is not None:
        release.force = body.force
    db.commit()
    db.refresh(release)
    return ReleaseOut.model_validate(release, from_attributes=True)


@admin_router.post("/{release_id}/publish", response_model=ReleaseOut)
def publish_release(release_id: int, body: PublishRequest, db: Session = Depends(get_db)):
    release = db.get(Release, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    release.published = body.published
    release.published_at = utcnow() if body.published else None
    db.commit()
    db.refresh(release)
    return ReleaseOut.model_validate(release, from_attributes=True)


@admin_router.delete("/{release_id}", response_model=dict)
def delete_release(release_id: int, db: Session = Depends(get_db)):
    release = db.get(Release, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    db.delete(release)
    db.commit()
    return {"ok": True}


@client_router.get("/latest-release", response_model=ReleaseOut | None)
def latest_release(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """客户端拉取最新已发布版本；无已发布版本返回 null。"""
    published = db.query(Release).filter(Release.published).all()
    if not published:
        return None
    latest = published[0]
    for r in published[1:]:
        if _compare_versions(r.version, latest.version) > 0:
            latest = r
    return ReleaseOut.model_validate(latest, from_attributes=True)
