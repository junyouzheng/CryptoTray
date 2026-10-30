import sys


def main() -> None:
    if "--check" in sys.argv:
        from crypto_tray.fetch import run_check

        raise SystemExit(run_check())
    from crypto_tray.runtime import run

    run()


if __name__ == "__main__":
    main()
