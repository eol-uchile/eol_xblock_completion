#!/usr/bin/env python
# -- coding: utf-8 --
# Python Standard Libraries
import codecs
import csv
import json
import logging
from datetime import datetime
from functools import partial
from time import time

# Installed packages (via pip)
from celery import task
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import Http404, JsonResponse
from django.utils.translation import gettext as _, ugettext_noop
from django.views.generic.base import View
from pytz import UTC
import six

# Edx dependencies
from common.djangoapps.util.file import course_filename_prefix_generator
from lms.djangoapps.courseware.access import has_access
from lms.djangoapps.courseware.courses import get_course_with_access
from lms.djangoapps.courseware.models import StudentModule
from lms.djangoapps.instructor import permissions
from lms.djangoapps.instructor_task.api_helper import submit_task, AlreadyRunningError
from lms.djangoapps.instructor_task.tasks_helper.runner import run_main_task, TaskProgress
from lms.djangoapps.instructor_task.tasks_base import BaseInstructorTask
from lms.djangoapps.instructor_task.models import ReportStore
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from xmodule.modulestore.django import modulestore

logger = logging.getLogger(__name__)

def task_process_data(request, data):
    course_key = CourseKey.from_string(data['course'])
    task_type = 'EOL_Xblock_Completion'
    if data['format']:
        task_type = 'EOL_Xblock_Completion_Resumen'
    task_class = process_data
    task_input = {'data': data }
    task_key = "EOL_Xblock_Completion_{}".format(data['course'])

    return submit_task(
        request,
        task_type,
        task_class,
        course_key,
        task_input,
        task_key)

@task(base=BaseInstructorTask, queue='edx.lms.core.low')
def process_data(entry_id, xmodule_instance_args):
    action_name = ugettext_noop('generated')
    task_fn = partial(generate, xmodule_instance_args)

    return run_main_task(entry_id, task_fn, action_name)

def generate(_xmodule_instance_args, _entry_id, course_id, task_input, action_name):
    """
    For a given `course_id`, generate a CSV file containing
    all student answers to a given problem, and store using a `ReportStore`.
    """
    start_time = time()
    start_date = datetime.now(UTC)
    num_reports = 1
    task_progress = TaskProgress(action_name, num_reports, start_time)
    current_step = {'step': 'XblockCompletion - Calculating students answers to problem'}
    task_progress.update_task_state(extra_meta=current_step)
    
    data = task_input.get('data')
    #filter_types = ['problem']

    report_store = ReportStore.from_config('GRADES_DOWNLOAD')
    csv_name = 'Reporte_de_Preguntas'
    if data['format']:
        csv_name = 'Reporte_de_Preguntas_Resumen'

    report_name = u"{course_prefix}_{csv_name}_{timestamp_str}.csv".format(
        course_prefix=course_filename_prefix_generator(course_id),
        csv_name=csv_name,
        timestamp_str=start_date.strftime("%Y-%m-%d-%H%M")
    )
    output_buffer = ContentFile('')
    if six.PY2:
        output_buffer.write(codecs.BOM_UTF8)
    csvwriter = csv.writer(output_buffer, delimiter=';', quoting=csv.QUOTE_ALL)

    csvwriter = XblockCompletionView()._build_student_data(data, csvwriter)

    current_step = {'step': 'XblockCompletion - Uploading CSV'}
    task_progress.update_task_state(extra_meta=current_step)

    output_buffer.seek(0)
    report_store.store(course_id, report_name, output_buffer)
    current_step = {
        'step': 'XblockCompletion - CSV uploaded',
        'report_name': report_name,
    }

    return task_progress.update_task_state(extra_meta=current_step)

def _get_utf8_encoded_rows(row):
    """
    Given a list of `rows` containing unicode strings, return a
    new list of rows with those strings encoded as utf-8 for CSV
    compatibility.
    """

    if six.PY2:
        return [six.text_type(item).encode('utf-8') for item in row]
    else:
        return [six.text_type(item) for item in row]

class XblockCompletionView(View):
    """
        Return a csv with progress students
    """
    @transaction.non_atomic_requests
    def dispatch(self, args, **kwargs):
        return super(XblockCompletionView, self).dispatch(args, **kwargs)

    def get(self, request, **kwargs):
        if not request.user.is_anonymous:
            data = self.validate_and_get_data(request)
            if data['format'] is None:
                logger.error("XblockCompletion - Falta parametro format o parametro incorrecto, user: {}, format: {}".format(request.user, request.GET.get('format', '')))
                return JsonResponse({'error': 'Falta parametro format o parametro incorrecto'})
            if data['course'] is None:
                logger.error("XblockCompletion - Falta parametro course o parametro incorrecto, user: {}, course: {}".format(request.user, request.GET.get('course', '')))
                return JsonResponse({'error': 'Falta parametro course o parametro incorrecto'})
            elif not self.have_permission(request.user, data['course']):
                logger.error("XblockCompletion - Usuario no tiene rol para esta funcionalidad, user: {}, course: {}".format(request.user, request.GET.get('course', '')))
                return JsonResponse({'error': 'Usuario no tiene rol para esta funcionalidad'})
            data['base_url'] = request.build_absolute_uri('')
            return self.get_context(request, data)
        else:
            logger.error("XblockCompletion - User is Anonymous")
        raise Http404()

    def get_context(self, request, data):
        try:
            task = task_process_data(request, data)
            success_status = 'El reporte de preguntas esta siendo creado, en un momento estará disponible para descargar.'
            return JsonResponse({"status": success_status, "task_id": task.task_id})
        except AlreadyRunningError:
            logger.error("XblockCompletion - Task Already Running Error, user: {}, data: {}".format(request.user, data))
            return JsonResponse({'error_task': 'AlreadyRunningError'})

    def have_permission(self, user, course_id):
        """
            Verify if the user is instructor
        """
        """
        any([
            request.user.is_staff,
            CourseStaffRole(course_key).has_user(request.user),
            CourseInstructorRole(course_key).has_user(request.user)
        ])
        """
        try:
            course_key = CourseKey.from_string(course_id)
            course = get_course_with_access(user, "load", course_key)
            data_researcher_access = user.has_perm(permissions.CAN_RESEARCH, course_key)
            return bool(has_access(user, 'instructor', course)) or bool(has_access(user, 'staff', course)) or data_researcher_access
        except Exception:
            return False

    def validate_and_get_data(self, request):
        """
            Verify format and course id
        """
        data = {'format': None, 'course': None}
        aux_resumen = request.GET.get('format', '')
        if aux_resumen == 'resumen':
            data['format'] = True
        elif aux_resumen == 'all':
            data['format'] = False
        # valida curso
        if request.GET.get("course", "") != "":
            # valida si existe el curso
            if self.validate_course(request.GET.get("course", "")):
                data['course'] = request.GET.get("course", "")
        
        return data

    def validate_course(self, id_curso):
        """
            Verify if course.id exists
        """
        from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
        try:
            aux = CourseKey.from_string(id_curso)
            return CourseOverview.objects.filter(id=aux).exists()
        except InvalidKeyError:
            return False

    def get_block_keys(self, course_key):
        smdat = list(StudentModule.objects.filter(
            course_id=course_key, 
            module_type="problem",
            student__courseenrollment__mode="honor",
            student__courseenrollment__is_active=1,
            state__contains="attempts"
            ).values('module_state_key').distinct())
        return [x['module_state_key'] for x in smdat]

    def get_user_states(self, course_key, block_key):
        smdat = list(StudentModule.objects.filter(
            course_id=course_key, 
            module_type="problem",
            module_state_key=block_key,
            student__courseenrollment__mode="honor",
            student__courseenrollment__is_active=1,
            state__contains="attempts"
            ).values('student__username', 'student__email','student__edxloginuser__run', 'state').distinct())
        return smdat

    def get_block_ancestors(self, xblock, store):
        """
        Returns information about the ancestors of an xblock.
        """
        ancestors = []

        def collect_ancestor_info(ancestor):
            """
            Collect xblock info regarding the specified xblock and its ancestors.
            """
            if ancestor.location.block_type != 'course':
                ancestors.append({'type': ancestor.location.block_type, 'display_name': ancestor.display_name})
                collect_ancestor_info(store.get_item(ancestor.parent))
        collect_ancestor_info(store.get_item(xblock.parent))
        return ancestors

    def _build_student_data(self, data, csvwriter):
        """
            Create list of list to make csv report
        """
        url_base = data['base_url']
        course_id = data['course']
        is_resumen = data['format']
        course_key = CourseKey.from_string(course_id)
        if is_resumen:
            header = ['Username', 'Email', 'Run', 'Seccion', 'SubSeccion', 'Unidad', 'Titulo', 'Intentos', 'Pts Ganados', 'Pts Posibles', 'block id', 'Has saved answers']
        else:
            header = ['Username', 'Email', 'Run', 'Seccion', 'SubSeccion', 'Unidad', 'Titulo', 'Pregunta', 'Respuesta Estudiante', 'Resp. Correcta', 'Intentos', 'Pts Ganados', 'Pts Posibles', 'Pts Total Componente', 'block id', 'Has saved answers', 'State']
        csvwriter.writerow(_get_utf8_encoded_rows(header))
        store = modulestore()
        list_blocks = self.get_block_keys(course_key)
        with store.bulk_operations(course_key):
            for block_key in list_blocks:
                try:
                    block_item = store.get_item(block_key)
                except Exception as e:
                    continue
                # assume all block_key are directly children of unit
                block_ancestors = self.get_block_ancestors(block_item, store)
                display_name = block_item.display_name.replace("\n", "")
                #jump_to_url = url_base + reverse('jump_to',kwargs={
                #            'course_id': course_id,
                #            'location': str(block_key)})
                # only problem block
                if is_resumen:
                    student_states  = self.get_user_states(course_key, block_key)
                    for response in student_states:
                        user_state = json.loads(response['state'])
                        # Check if correct_map exist
                        if user_state.get('correct_map', None) is None:
                            continue
                        # Total points of a block
                        total_points = getattr(block_item, 'weight', None)
                        if total_points is None:
                            total_points = float( user_state['score']['raw_possible'] )
                        # Points obtained for each question
                        pts_question = float( total_points / len(user_state['correct_map']))
                        report = {}
                        report['username'] = response['student__username']
                        report['email'] = response['student__email']
                        report['user_rut'] = response['student__edxloginuser__run']
                        report['attempts'] = user_state['attempts']
                        report['gained'] = round(user_state['score']['raw_earned'] * pts_question, 2),
                        report['total'] =  round(total_points, 2)
                        row = [
                            response['student__username'],
                            response['student__email'],
                            response['student__edxloginuser__run'],
                            block_ancestors[2]['display_name'],
                            block_ancestors[1]['display_name'],
                            block_ancestors[0]['display_name'],
                            display_name,
                            user_state['attempts'],
                            round(float(user_state['score']['raw_earned'] * pts_question), 2),
                            round(float(total_points), 2),
                            str(block_key)
                            ]
                        if 'has_saved_answers' in user_state and user_state['has_saved_answers']:
                            row.append('has_saved_answers')
                        csvwriter.writerow(row)
                else:
                    for response in self.generate_report_data(block_item):
                        if response is None:
                            continue
                        row = [                            
                            response['username'],
                            response['email'],
                            response['user_rut'],
                            block_ancestors[2]['display_name'],
                            block_ancestors[1]['display_name'],
                            block_ancestors[0]['display_name'],
                            display_name,
                            response['question'].replace("\n", ""),
                            response['answer'].replace("\n", ""),
                            response['correct_answer'].replace("\n", ""),
                            response['attempts'],
                            response['gained'],
                            response['possible'],
                            response['total'],
                            str(block_key),
                            'has_saved_answers' if response['has_saved_answers'] else ''
                            ]
                        if response['state']:
                            row.append(response['state'])
                        csvwriter.writerow(row)
        return csvwriter

    def generate_report_data(self, block):
        """
        Return a list of student responses to this block in a readable way.
        Arguments:
            user_state_iterator: iterator over UserStateClient objects.
                E.g. the result of user_state_client.iter_all_for_block(block_key)
            limit_responses (int|None): maximum number of responses to include.
                Set to None (default) to include all.
        Returns:
            each call returns a tuple like:
            ("username", {
                           "Question": "2 + 2 equals how many?",
                           "Answer": "Four",
                           "Answer ID": "98e6a8e915904d5389821a94e48babcf_10_1"
            })
        https://github.com/openedx/edx-platform/blob/open-release/olive.master/xmodule/capa/capa_problem.py
        """
        from capa.capa_problem import LoncapaProblem, LoncapaSystem

        capa_system = LoncapaSystem(
            ajax_url=None,
            # TODO set anonymous_student_id to the anonymous ID of the user which answered each problem
            # Anonymous ID is required for Matlab, CodeResponse, and some custom problems that include
            # '$anonymous_student_id' in their XML.
            # For the purposes of this report, we don't need to support those use cases.
            anonymous_student_id=None,
            cache=None,
            can_execute_unsafe_code=lambda: None,
            get_python_lib_zip=None,
            DEBUG=None,
            filestore=block.runtime.resources_fs,
            i18n=block.runtime.service(block, "i18n"),
            node_path=None,
            render_template=None,
            seed=1,
            STATIC_URL=None,
            xqueue=None,
            matlab_api_key=None,
        )
        student_states  = self.get_user_states(block.location.course_key, block.location)
        for response in student_states:
            user_state = json.loads(response['state'])
            if 'student_answers' not in user_state:
                continue
            try:
                lcp = LoncapaProblem(
                    problem_text=block.data,
                    id=block.location.html_id(),
                    capa_system=capa_system,
                    # We choose to run without a fully initialized CapaModule
                    capa_module=None,
                    state={
                        'done': user_state.get('done'),
                        'correct_map': user_state.get('correct_map'),
                        'student_answers': user_state.get('student_answers'),
                        'has_saved_answers': user_state.get('has_saved_answers'),
                        'input_state': user_state.get('input_state'),
                        'seed': user_state.get('seed'),
                    },
                    seed=user_state.get('seed'),
                    # extract_tree=False allows us to work without a fully initialized CapaModule
                    # We'll still be able to find particular data in the XML when we need it
                    extract_tree=False,
                )
                for answer_id, orig_answers in lcp.student_answers.items():
                    # Some types of problems have data in lcp.student_answers that isn't in lcp.problem_data.
                    # E.g. formulae do this to store the MathML version of the answer.
                    # We exclude these rows from the report because we only need the text-only answer.
                    if answer_id.endswith('_dynamath'):
                        continue
                    # Check if correct_map exist
                    if user_state.get('correct_map', None) is None:
                        continue
                    question_text = lcp.find_question_label(answer_id)
                    answer_text = lcp.find_answer_text(answer_id, current_answer=orig_answers)
                    correct_answer_text = lcp.find_correct_answer_text(answer_id)

                    report = {
                        'answer_id': answer_id,
                        'question': question_text or '',
                        'answer': answer_text or '',
                        'correct_answer': correct_answer_text or ''
                    }
                    # Total points of a block
                    total_points = getattr(block, 'weight', None)
                    if total_points is None:
                        total_points = float(user_state['score']['raw_possible'])
                    # Points obtained for each question
                    pts_question = round(float( total_points  / len(user_state['correct_map'])), 2)
                    report['username'] = response['student__username']
                    report['email'] = response['student__email']
                    report['user_rut'] = response['student__edxloginuser__run']
                    report['attempts'] = user_state['attempts']
                    # Points earned by the user on a particular question
                    report['gained'] = pts_question if user_state['correct_map'][answer_id]['correctness'] == "correct" else float(0)
                    # Possible points for each question
                    report['possible'] = pts_question
                    report['total'] = round(float(total_points), 2)
                    report['has_saved_answers'] = user_state.get('has_saved_answers', None)
                    report['state'] = None
                    yield report
            except Exception as e:
                logger.error("XblockCompletionView - Error to create xml problem, block id: {}, error: {}".format(str(block.location), str(e)))
                # Check if correct_map exist
                if user_state.get('correct_map', None) is None:
                    continue
                # Total points of a block
                total_points = getattr(block, 'weight', None)
                if total_points is None:
                    total_points = float(user_state['score']['raw_possible'])
                # Points obtained for each question
                pts_question = round(float( total_points  / len(user_state['correct_map'])), 2)
                report = {
                    'answer_id': '',
                    'question': '',
                    'answer': '',
                    'correct_answer': ''
                }
                report['username'] = response['student__username']
                report['email'] = response['student__email']
                report['user_rut'] = response['student__edxloginuser__run']
                report['attempts'] = user_state.get('attempts', '')
                # Points earned by the user on a particular question
                report['gained'] = pts_question if user_state['correct_map'][answer_id]['correctness'] == "correct" else float(0)
                # Possible points for each question
                report['possible'] = pts_question
                report['total'] = round(float(total_points), 2)
                report['has_saved_answers'] = user_state.get('has_saved_answers', None)
                report['state'] = response['state']
                yield report
            
