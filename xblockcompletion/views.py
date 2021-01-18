#!/usr/bin/env python
# -- coding: utf-8 --

from django.conf import settings
from django.shortcuts import render
from django.views.generic.base import View
from completion.models import BlockCompletion
from opaque_keys.edx.keys import CourseKey, UsageKey, LearningContextKey
from django.http import Http404, HttpResponse, JsonResponse

from collections import OrderedDict, defaultdict
from django.contrib.auth import get_user_model
from xmodule.modulestore.django import modulestore
from lms.djangoapps.course_blocks.api import get_course_blocks
from lms.djangoapps.instructor_task.tasks_helper.grades import  ProblemResponses
from lms.djangoapps.instructor_analytics.basic import list_problem_responses, get_response_state
from django.core.exceptions import FieldError
from django.contrib.auth.models import User
from django.utils.translation import gettext as _
from .utils import get_data_course
import requests
import json
import logging
import unicodecsv as csv
from django.urls import reverse
from lms.djangoapps.courseware.models import StudentModule
from courseware.courses import get_course_by_id, get_course_with_access
from courseware.access import has_access
from opaque_keys import InvalidKeyError
logger = logging.getLogger(__name__)

class XblockCompletionView(View):
    """
        Return a csv with progress students
    """
    
    def get(self, request):
        if not request.user.is_anonymous:
            data = self.validate_and_get_data(request)
            if data['format'] is None:
                return JsonResponse({'error': 'Falta parametro format o parametro incorrecto'})
            if data['course'] is None:
                return JsonResponse({'error': 'Falta parametro course o parametro incorrecto'})
            elif not self.have_permission(request.user, data['course']):
                return JsonResponse({'error': 'Usuario no tiene rol para esta funcionalidad'})
            course_id = data['course']
            students = self.get_all_enrolled_users(course_id)
            course_structure = get_data_course(course_id)
            student_data = self._build_student_data(request, students, course_structure, data['format'], course_id)
            return self.export(student_data)
        else:
            logger.error("XblockCompletion - User is Anonymous")
        raise Http404()

    def have_permission(self, user, course_id):
        """
            Verify if the user is instructor
        """
        try:
            course_key = CourseKey.from_string(course_id)
            course = get_course_with_access(user, "load", course_key)
            return bool(has_access(user, 'instructor', course)) or bool(has_access(user, 'staff', course))
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

    def get_all_states(self, course_id, filter_types):
        """
            Get all student module of course
        """
        course_key = CourseKey.from_string(course_id)
        smdat = StudentModule.objects.filter(course_id=course_key, module_type__in=filter_types).order_by('student__username').values('student__username', 'state', 'module_state_key')
        response = defaultdict(list)
        for module in smdat:
            response[str(module['module_state_key'])].append({'username': module['student__username'], 'state': module['state']})

        return response

    def _build_student_data(self, request, students, course_structure, is_resumen, course_id):
        """
            Create list of list to make csv report
        """
        course_key = CourseKey.from_string(course_id)
        filter_types = ['problem']
        if is_resumen:
            student_data = [['Titulo', 'Username', 'Email', 'Run', 'Seccion', 'SubSeccion', 'Unidad', 'Intentos', 'Pts Ganados', 'Pts Posibles', 'Url', 'State', 'block_id']]
        else:
            student_data = [['Titulo', 'Username', 'Email', 'Run', 'Seccion', 'SubSeccion', 'Unidad', 'Pregunta', 'Respuesta Estudiante', 'Resp. Correcta', 'Intentos', 'Pts Ganados', 'Pts Posibles', 'Pts Total Componente', 'Url', 'block_id']]
        max_count = None
        store = modulestore()
        i=0
        j=0
        k=0
        student_states = self.get_all_states(course_id, filter_types)
        if 'child_info' in course_structure and len(student_states) > 0:
            for section in course_structure['child_info']['children']:
                i = i + 1
                if 'child_info' in section:
                    for subsection in section['child_info']['children']:
                        j = j + 1
                        if 'child_info' in subsection:
                            for unit in subsection['child_info']['children']:
                                k = k + 1
                                if 'child_info' in unit:
                                    for block in unit['child_info']['children']:
                                        with store.bulk_operations(course_key):
                                            block_key = UsageKey.from_string(block['id'])
                                            if filter_types is not None and block_key.block_type not in filter_types:
                                                continue
                                            block_item = store.get_item(block_key)
                                            generated_report_data = defaultdict(list)
                                            if not is_resumen:
                                                generated_report_data = self.get_report_xblock(block_key, student_states[block['id']], block_item)
                                            if generated_report_data is None:
                                                continue
                                            jumo_to_url = request.build_absolute_uri(reverse(
                                                    'jump_to',
                                                    kwargs={
                                                        'course_id': course_id,
                                                        'location': block['id']}))
                                            for response in student_states[block['id']]:
                                                if response['username'] not in students:
                                                    continue
                                                if is_resumen:
                                                    if block_key.block_type != 'problem':
                                                        pass
                                                    else:
                                                        responses = self.set_data_is_resumen(
                                                            block_item.display_name, 
                                                            block['id'],
                                                            response,
                                                            str(i) + '.' + section['display_name'],
                                                            str(i) + '.' + str(j) + '.' + subsection['display_name'],
                                                            str(i) + '.' + str(j) + '.' + str(k) + '.' + unit['display_name'],
                                                            students, jumo_to_url
                                                            )
                                                        if responses:
                                                            student_data.append(responses)
                                                else:
                                                    # A human-readable location for the current block
                                                    # A machine-friendly location for the current block
                                                    # A block that has a single state per user can contain multiple responses
                                                    # within the same state.
                                                    if block_key.block_type != 'problem':
                                                        pass
                                                    else:
                                                        user_states = generated_report_data.get(response['username'])
                                                        if user_states:
                                                            responses = self.set_data_is_all(
                                                                    block_item.display_name, 
                                                                    block['id'],
                                                                    response,
                                                                    str(i) + '.' + section['display_name'],
                                                                    str(i) + '.' + str(j) + '.' + subsection['display_name'],
                                                                    str(i) + '.' + str(j) + '.' + str(k) + '.' + unit['display_name'],
                                                                    students,
                                                                    user_states, jumo_to_url
                                                                    )
                                                            if responses:
                                                                student_data = student_data + responses
        return student_data

    def set_data_is_resumen(self, title, block_id, response, section, subsection, unit, students, jumo_to_url):
        """
            Create a row according 
            ['Titulo', 'Username', 'Email', 'Run', 'Seccion', 'SubSeccion', 'Unidad', 'Intentos', 'Pts Ganados', 'Pts Posibles','url', 'State', 'block_id']
        """
        raw_state = json.loads(response['state'])
        responses = []
        if 'attempts' in raw_state:
            responses = [
                title,
                response['username'], 
                students[response['username']]['email'], 
                students[response['username']]['rut'],
                section,
                subsection,
                unit,
                raw_state['attempts'] ,
                raw_state['score']['raw_earned'],
                raw_state['score']['raw_possible'],
                jumo_to_url,
                response['state'],
                block_id
                ]

        return responses
    
    def set_data_is_all(self, title, block_id, response, section, subsection, unit, students, user_states, jumo_to_url):
        """
            Create a row according 
            ['Titulo', 'Username', 'Email', 'Run', 'Seccion', 'SubSeccion', 'Unidad', 'Pregunta', 'Respuesta Estudiante', 'Resp. Correcta', 'Intentos', 'Pts Ganados', 'Pts Posibles', 'Pts Total Componente', 'block_id']
        """
        raw_state = json.loads(response['state'])
        if 'attempts' not in raw_state:
            return []
        aux_response = []

        # For each response in the block, copy over the basic data like the
        # title, location, block_key and state, and add in the responses
        pts_question = int(raw_state['score']['raw_possible']) / len(user_states)
        for user_state in user_states:
            correct_answer = ''
            if _("Correct Answer") in user_state:
                correct_answer = user_state[_("Correct Answer")]
            responses = [
                title,
                response['username'], 
                students[response['username']]['email'], 
                students[response['username']]['rut'],
                section,
                subsection,
                unit,
                user_state[_("Question")],
                user_state[_("Answer")],
                correct_answer,
                raw_state['attempts'],
                pts_question if int(raw_state['score']['raw_earned']) > 0 and user_state[_("Answer")] == correct_answer else '0',
                pts_question,
                raw_state['score']['raw_possible'],
                jumo_to_url,
                block_id
                ]
            aux_response.append(responses)
        return aux_response

    def get_all_enrolled_users(self, course_key):
        """
            Get all enrolled student 
        """
        students = {}
        try:
            enrolled_students = User.objects.filter(
                courseenrollment__course_id=course_key,
                courseenrollment__is_active=1
            ).values('username', 'email', 'edxloginuser__run')
        except FieldError:
            enrolled_students = User.objects.filter(
                courseenrollment__course_id=course_key,
                courseenrollment__is_active=1
            ).values('username', 'email')
        
        for user in enrolled_students:
            students[user['username']] = {'email': user['email'], 'rut': user['edxloginuser__run'] if 'edxloginuser__run' in user else ''}
        return students
    
    def get_report_xblock(self, block_key, user_states, block):
        """
        # Blocks can implement the generate_report_data method to provide their own
        # human-readable formatting for user state.
        """
        generated_report_data = defaultdict(list)

        if block_key.block_type != 'problem':
            return None
        elif hasattr(block, 'generate_report_data'):
            try:
                for username, state in self.generate_report_data(user_states, block):
                    generated_report_data[username].append(state)
            except NotImplementedError:
                logger.info('XblockCompletion - block {} dont have implemented generate_report_data'.format(str(block_key)))
                pass
        return generated_report_data

    def export(self, data_student):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="xblock_completion.csv"'

        writer = csv.writer(
            response,
            delimiter=';',
            dialect='excel',
            encoding='utf-8')
        
        writer.writerows(data_student)

        return response
    
    def generate_report_data(self, user_states, block):
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
        """
        from capa.capa_problem import LoncapaProblem, LoncapaSystem

        if block.category != 'problem':
            raise NotImplementedError()

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

        for response in user_states:
            user_state = json.loads(response['state'])
            if 'student_answers' not in user_state:
                continue

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

                question_text = lcp.find_question_label(answer_id)
                answer_text = lcp.find_answer_text(answer_id, current_answer=orig_answers)
                correct_answer_text = lcp.find_correct_answer_text(answer_id)

                report = {
                    _("Answer ID"): answer_id,
                    _("Question"): question_text,
                    _("Answer"): answer_text,
                }
                if correct_answer_text is not None:
                    report[_("Correct Answer")] = correct_answer_text
                yield (response['username'], report)