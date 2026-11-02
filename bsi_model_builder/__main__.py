"""
python -m bsi_model_builder            -> desktop app
python -m bsi_model_builder build ...  -> command line
"""
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("build", "check", "selftest", "template", "takeoff", "--help", "-h", "--version"):
        from .cli import main as cli_main
        return cli_main(argv)
    from .ui.app import main as ui_main
    return ui_main()


if __name__ == "__main__":
    sys.exit(main() or 0)
