import argparse
import csv
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.db.session import get_connection  # noqa: E402


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def import_communities(csv_path: Path, city: str) -> dict:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV 文件不存在：{csv_path}")

    inserted = 0
    updated = 0
    skipped = 0

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle, get_connection() as conn:
        reader = csv.DictReader(handle)
        required = {"id", "name", "street", "area", "create_time", "modify_time"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV 缺少字段：{', '.join(sorted(missing))}")

        for row in reader:
            name = _clean(row.get("name"))
            if not name:
                skipped += 1
                continue

            community_id = int(row["id"]) if _clean(row.get("id")) else None
            payload = (
                name,
                _clean(row.get("street")),
                _clean(row.get("area")),
                _clean(row.get("create_time")),
                _clean(row.get("modify_time")),
                city,
            )

            if community_id is not None:
                exists = conn.execute("SELECT id FROM communities WHERE id = ?", (community_id,)).fetchone()
                if exists:
                    conn.execute(
                        """
                        UPDATE communities
                        SET name = ?, street = ?, area = ?, create_time = ?, modify_time = ?, city = ?
                        WHERE id = ?
                        """,
                        payload + (community_id,),
                    )
                    updated += 1
                else:
                    conn.execute(
                        """
                        INSERT INTO communities(id, name, street, area, create_time, modify_time, city)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (community_id,) + payload,
                    )
                    inserted += 1
            else:
                conn.execute(
                    """
                    INSERT INTO communities(name, street, area, create_time, modify_time, city)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
                inserted += 1

        updated_orders = conn.execute(
            """
            UPDATE orders
            SET area = (
                    SELECT c.area
                    FROM communities c
                    WHERE c.name = orders.residential
                      AND COALESCE(c.city, ?) = orders.city
                    ORDER BY c.id
                    LIMIT 1
                ),
                street = (
                    SELECT c.street
                    FROM communities c
                    WHERE c.name = orders.residential
                      AND COALESCE(c.city, ?) = orders.city
                    ORDER BY c.id
                    LIMIT 1
                ),
                modify_time = CURRENT_TIMESTAMP
            WHERE COALESCE(status, 'normal') = 'normal'
              AND city = ?
              AND EXISTS (
                    SELECT 1
                    FROM communities c
                    WHERE c.name = orders.residential
                      AND COALESCE(c.city, ?) = orders.city
                )
            """,
            (city, city, city, city),
        ).rowcount

        conn.commit()

    return {
        "csv_path": str(csv_path),
        "city": city,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "updated_orders": updated_orders,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="导入小区字典并回填订单区域/街道")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--city", default=settings.default_city)
    args = parser.parse_args()
    print(import_communities(args.csv_path, args.city))


if __name__ == "__main__":
    main()
