from sqlalchemy import text
from app.settings import settings

from app.database import get_source_engine

SOURCE_SCHEMA = "minsheng"
SOURCE_TABLE = "民生民情信息_治理工作副本_20261012"


def get_intake_profile() -> dict[str, object]:
    """Read only dataset metadata; legacy geometry is counted for audit but never reused."""
    engine = get_source_engine()
    if engine is None:
        return {"dataset": "尚未导入接诉即办数据", "source_type": "本地 SQLite", "primary_key": "—", "content_field": "—", "read_only": True, "legacy_geometry_reused": False, "total": 0, "with_content": 0, "without_content": 0, "legacy_mapped": 0}
    with engine.connect() as connection:
        row = connection.execute(
            text(
                f'''SELECT
                    count(*) AS total,
                    count(*) FILTER (WHERE nullif(btrim("主要内容"), '') IS NOT NULL) AS with_content,
                    count(*) FILTER (WHERE nullif(btrim("主要内容"), '') IS NULL) AS without_content,
                    count(*) FILTER (WHERE "是否落图" IS TRUE) AS legacy_mapped,
                    min("业务主键") AS min_id,
                    max("业务主键") AS max_id
                FROM "{SOURCE_SCHEMA}"."{SOURCE_TABLE}"
                WHERE "数据来源" = :source'''
            ),
            {"source": "接诉即办"},
        ).mappings().one()
        return {
            "dataset": f"{SOURCE_SCHEMA}.{SOURCE_TABLE}",
            "source_type": "接诉即办",
            "primary_key": "业务主键",
            "content_field": "主要内容",
            "read_only": True,
            "legacy_geometry_reused": False,
            **dict(row),
        }
