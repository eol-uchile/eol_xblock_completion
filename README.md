# Eol Xblock Completion


![Coverage Status](/coverage-badge.svg)


Question report in CSV

# Install

```
docker-compose exec lms pip install -e /openedx/requirements/eol_xblock_completion
docker-compose exec lms_worker pip install -e /openedx/requirements/eol_xblock_completion
```

# Install Theme

To enable the export eol xblock completion report, add the following code to your theme. This includes a conditional check to ensure the template only renders if the app is installed.

- _../themes/your_theme/lms/templates/instructor/instructor_dashboard_2/data_download.html_

    <%
    xblockcompletion_url = None
    xblockcompletion_traceback = None
    try:
      xblockcompletion_url = reverse('xblockcompletion-data:data')
    except Exception as e:
      if settings.DEBUG:
        xblockcompletion_traceback = traceback.format_exc()
    %>
    %if xblockcompletion_traceback:
      <div class="xblockcompletion_traceback" hidden>
        <pre>${xblockcompletion_traceback}</pre>
      </div>
    %elif xblockcompletion_url:
      <%include file="eol_xblock_completion.html"/>
    %endif

### Adding new translations:

To extract and update any new translatable text, run the update command below. After manually filling in the new translations, run the compile command to update the .mo translation files.

### Commands

**Update**

    docker run -it --rm -w /code -v $(pwd):/code python:3.8 bash
    pip install -r requirements-i18n.in
    make update_translations

**Compile**

    docker run -it --rm -w /code -v $(pwd):/code python:3.8 bash
    pip install -r requirements-i18n.in
    make compile_translations

## TESTS
**Prepare tests:**

- Install **act** following the instructions in [https://nektosact.com/installation/index.html](https://nektosact.com/installation/index.html)

**Run tests:**
- In a terminal at the root of the project
    ```
    act -W .github/workflows/pythonapp.yml
    ```
