import argparse
import json

from .dependencies import get_ingestion_service
from .models import IngestRequest


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest YouTube product review comments")
    parser.add_argument("product", help="Canonical product name, e.g. 'Microsoft Teams'")
    parser.add_argument("--query", help="YouTube search query")
    parser.add_argument("--max-videos", type=int, default=5)
    parser.add_argument("--max-comments", type=int, default=200)
    parser.add_argument("--include-replies", action="store_true")
    args = parser.parse_args()

    result = get_ingestion_service().ingest(
        IngestRequest(
            product=args.product,
            query=args.query,
            max_videos=args.max_videos,
            max_comments_per_video=args.max_comments,
            include_replies=args.include_replies,
        )
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()

