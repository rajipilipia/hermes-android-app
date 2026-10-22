"""Reversible project-owned launcher; imports no original runtime before validation."""
from .production_composition import main, run, validate_launch

if __name__ == '__main__':
    main()
