from worker.main import run_queue


def main() -> None:
    run_queue("document_analysis")


if __name__ == "__main__":
    main()
