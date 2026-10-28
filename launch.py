"""Absolute entry point for Windows startup, independent of working directory."""
import sys


def run():
    if '--version' in sys.argv:
        from desktop_pet.version import __version__
        if sys.stdout is not None:
            print(__version__)
        return
    if '--smoke-test' in sys.argv:
        import argparse
        from desktop_pet.diagnostics import packaged_smoke_test
        parser = argparse.ArgumentParser()
        parser.add_argument('--smoke-test', required=True)
        args = parser.parse_args()
        packaged_smoke_test(args.smoke_test)
        return
    from desktop_pet.app import main
    main()

if __name__ == '__main__':
    run()
