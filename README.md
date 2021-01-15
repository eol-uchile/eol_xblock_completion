# Eol Xblock Completion

Question report in CSV

# Install

    docker-compose exec lms pip install -e /openedx/requirements/eol_xblock_completion

## TESTS
**Prepare tests:**

    > cd .github/
    > docker-compose run lms /openedx/requirements/eol_xblock_completion/.github/test.sh
