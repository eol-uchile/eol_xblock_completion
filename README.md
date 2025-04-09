# Eol Xblock Completion


![Coverage Status](/coverage-badge.svg)


Question report in CSV

# Install

```
docker-compose exec lms pip install -e /openedx/requirements/eol_xblock_completion
docker-compose exec lms_worker pip install -e /openedx/requirements/eol_xblock_completion
```

# Install Theme

To enable export Eol Xblock Completion button in your theme add next file and/or lines of code:

- _../themes/your_theme/lms/templates/instructor/instructor_dashboard_2/data_download.html_

    1. **Add the script and css**
    ```
    <script type="text/javascript" src="${static.url('xblockcompletion/js/xblockcompletion.js')}"></script>
    <link rel="stylesheet" type="text/css" href="${static.url('xblockcompletion/css/xblockcompletion.css')}"/>
    ```

    2. **Add html button**
    ```
    %if 'has_xblockcompletion' in section_data and section_data['has_xblockcompletion']:
        <div class='xblockcompletion-report'>
            <hr>
            <h4 class="hd hd-4">Reporte de preguntas</h4>
            <p>Existen dos maneras para generar reportes de preguntas en formato CSV: </p>
            <p><b>- Modo resumen/compacto</b>: Genera un reporte de todos los bloques tipo pregunta mostrando los intentos, puntaje ganado y puntaje posible del bloque de cada estudiante.</p>
            <p><b>- Modo Completo</b>: Genera un reporte de todas las preguntas de los bloques tipo pregunta mostrando la pregunta, respuesta del estudiante, respuesta correcta, intentos, puntaje ganado y puntaje posible del bloque.</p>
            <p><input onclick="generate_report_xblockcompletion(this)" type="button" name="xblockcompletion-report-resumen" value="Reporte Modo Resumen" data-endpoint="${ section_data['xblockcompletion_url_resumen'] }"/>
            <input onclick="generate_report_xblockcompletion(this)" type="button" name="xblockcompletion-report-all" value="Reporte Modo Completo" data-endpoint="${ section_data['xblockcompletion_url_all'] }"/></p>
            <div class="xblockcompletion-success-msg" id="xblockcompletion-success-msg"></div>
            <div class="xblockcompletion-warning-msg" id="xblockcompletion-warning-msg"></div>
            <div class="xblockcompletion-error-msg" id="xblockcompletion-error-msg"></div>
            <p>Para una mejor visualización y manejo de los datos en el Excel, puede ver un mini tutorial haciendo <a target="_blank" href="https://youtu.be/v4ecUuetKDo">click aqui</a>.</p>
        </div>
    %endif
    ```

- In your edx-platform add the following code in the function '_section_data_download' in _edx-platform/lms/djangoapps/instructor/views/instructor_dashboard.py_
    ```
    try:
        import urllib
        from xblockcompletion import views
        section_data['has_xblockcompletion'] = True
        section_data['xblockcompletion_url_resumen'] = '{}?{}'.format(reverse('xblockcompletion-data:data'), urllib.parse.urlencode({'format': 'resumen', 'course': str(course_key)}))
        section_data['xblockcompletion_url_all'] = '{}?{}'.format(reverse('xblockcompletion-data:data'), urllib.parse.urlencode({'format': 'all', 'course': str(course_key)}))
    except ImportError:
        section_data['has_xblockcompletion'] = False
    ```

## TESTS
**Prepare tests:**

- Install **act** following the instructions in [https://nektosact.com/installation/index.html](https://nektosact.com/installation/index.html)

**Run tests:**
- In a terminal at the root of the project
    ```
    act -W .github/workflows/pythonapp.yml
    ```
