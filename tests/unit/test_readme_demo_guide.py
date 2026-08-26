from pathlib import Path


def test_readme_documents_local_worker_and_remote_cleanup() -> None:
    readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")

    for required in (
        "REQUIRED_WORKER_QUEUES",
        '["document_analysis"]',
        "JWT_LEEWAY_SECONDS=5",
        "scripts.remote_demo_smoke",
        "scripts.cleanup_remote_demo",
        "REMOTE_DEMO_OK",
        "REMOTE_DEMO_CLEANUP_OK",
    ):
        assert required in readme, "AC-T7-LOCAL-DEMO-GUIDE"
