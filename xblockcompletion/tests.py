#!/usr/bin/env python
# -*- coding: utf-8 -*-
from mock import patch, Mock, MagicMock
from collections import namedtuple
from django.urls import reverse
from django.test import TestCase, Client
from django.test import Client
from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from urllib.parse import parse_qs
from opaque_keys.edx.locator import CourseLocator
from common.djangoapps.student.tests.factories import CourseEnrollmentAllowedFactory, UserFactory, CourseEnrollmentFactory
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from common.djangoapps.student.roles import CourseInstructorRole, CourseStaffRole
from common.djangoapps.student.tests.factories import CourseAccessRoleFactory
from .views import XblockCompletionView, generate
from rest_framework_jwt.settings import api_settings
from django.test.utils import override_settings
from django.utils.translation import gettext as _
from lms.djangoapps.instructor_task.models import ReportStore
import re
import json
import urllib.parse
import uuid


class TestXblockCompletionView(ModuleStoreTestCase):
    def setUp(self):
        super(TestXblockCompletionView, self).setUp()
        self.course = CourseFactory.create(
            org='mss',
            course='999',
            display_name='2021',
            emit_signals=True)
        aux = CourseOverview.get_from_id(self.course.id)
        with self.store.bulk_operations(self.course.id, emit_signals=False):
            self.chapter = ItemFactory.create(
                parent_location=self.course.location,
                category="chapter",
            )
            self.section = ItemFactory.create(
                parent_location=self.chapter.location,
                category="sequential",
            )
            self.subsection = ItemFactory.create(
                parent_location=self.section.location,
                category="vertical",
            )
            self.items = [
                ItemFactory.create(
                    parent_location=self.subsection.location,
                    category="problem"
                )
                for __ in range(3)
            ]
        with patch('common.djangoapps.student.models.cc.User.save'):
            # staff user
            self.client_instructor = Client()
            self.client_student = Client()
            self.user_instructor = UserFactory(
                username='instructor',
                password='12345',
                email='instructor@edx.org',
                is_staff=True)
            role = CourseInstructorRole(self.course.id)
            role.add_users(self.user_instructor)
            self.client_instructor.login(
                username='instructor', password='12345')
            self.student = UserFactory(
                username='student',
                password='test',
                email='student@edx.org')
            # Enroll the student in the course
            CourseEnrollmentFactory(
                user=self.student, course_id=self.course.id, mode='honor')
            self.client_student.login(
                username='student', password='test')
            # Create and Enroll data researcher user
            self.data_researcher_user = UserFactory(
                username='data_researcher_user',
                password='test',
                email='data.researcher@edx.org')
            CourseEnrollmentFactory(
                user=self.data_researcher_user,
                course_id=self.course.id, mode='audit')
            CourseAccessRoleFactory(
                course_id=self.course.id,
                user=self.data_researcher_user,
                role='data_researcher',
                org=self.course.id.org
            )
            self.client_data_researcher = Client()
            self.assertTrue(self.client_data_researcher.login(username='data_researcher_user', password='test'))

    def _verify_csv_file_report(self, report_store, expected_data):
        """
        Verify course survey data.
        """
        report_csv_filename = report_store.links_for(self.course.id)[0][0]
        report_path = report_store.path_to(self.course.id, report_csv_filename)
        with report_store.storage.open(report_path) as csv_file:
            csv_file_data = csv_file.read()
            # Removing unicode signature (BOM) from the beginning
            csv_file_data = csv_file_data.decode("utf-8-sig")
            for data in expected_data:
                self.assertIn(data, csv_file_data)
    
    def _verify_csv_file_report_notIn(self, report_store, expected_data):
        """
        Verify course survey data.
        """
        report_csv_filename = report_store.links_for(self.course.id)[0][0]
        report_path = report_store.path_to(self.course.id, report_csv_filename)
        with report_store.storage.open(report_path) as csv_file:
            csv_file_data = csv_file.read()
            # Removing unicode signature (BOM) from the beginning
            csv_file_data = csv_file_data.decode("utf-8-sig")
            for data in expected_data:
                self.assertNotIn(data, csv_file_data)


    def test_xblockcompletion_get(self):
        """
            Test xblockcompletion view
        """
        response = self.client_instructor.get(reverse('xblockcompletion-data:data'))
        request = response.request
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request['PATH_INFO'], '/xblockcompletion/data')

    def test_xblockcompletion_get_resumen(self):
        """
        test to generate course survey report
        and then test the report authenticity.
        """
        from lms.djangoapps.courseware.models import StudentModule
        data = {'format': True, 'course': str(self.course.id), 'base_url':'this_is_a_url'}
        task_input = {'data': data }
        module = StudentModule(
            module_state_key=self.items[0].location,
            student=self.student,
            course_id=self.course.id,
            module_type='problem',
            state='{"score": {"raw_earned": 0, "raw_possible": 3}, "seed": 1, "attempts":1,"has_saved_answers": true}')
        module.save()
        module2 = StudentModule(
            module_state_key=self.items[1].location,
            student=self.student,
            course_id=self.course.id,
            module_type='problem',
            state='{"score": {"raw_earned": 0, "raw_possible": 3}, "seed": 1}')
        module2.save()
        with patch('lms.djangoapps.instructor_task.tasks_helper.runner._get_current_task'):
            result = generate(
                None, None, self.course.id,
                task_input, 'EOL_Xblock_Completion'
            )
        report_store = ReportStore.from_config(config_name='GRADES_DOWNLOAD')
        header_row = ";".join(['"Username"', '"Email"', '"Run"', '"Seccion"', '"SubSeccion"', '"Unidad"', '"Titulo"', '"Intentos"', '"Pts Ganados"', '"Pts Posibles"', '"block id"', '"Has saved answers"'])
        student1_row = ";".join([
            '"{}"'.format(self.student.username),
            '"{}"'.format(self.student.email),
            '""',
            '"{}"'.format(self.chapter.display_name),
            '"{}"'.format(self.section.display_name),
            '"{}"'.format( self.subsection.display_name),
            '"{}"'.format(self.items[0].display_name),
            '"1"','"0"','"3"','"{}"'.format(str(self.items[0].location)) ,'"has_saved_answers"'
        ])
        expected_data = [header_row, student1_row]
        self._verify_csv_file_report(report_store, expected_data)
        self._verify_csv_file_report_notIn(report_store, [str(self.items[1].location)])

    @patch("xblockcompletion.views.XblockCompletionView.generate_report_data")
    def test_xblockcompletion_get_all_data(self, report):
        """
            Test xblockcompletion view all data
        """
        state_1 = {
            'answer_id': 'answer_id',
            'question': 'question_text',
            'answer': 'answer_text',
            'correct_answer': 'correct_answer_text',
            'username': self.student.username,
            'email': self.student.email,
            'user_rut': '',
            'attempts': '1',
            'gained': '0',
            'possible': '1.0',
            'total': '3',
            'has_saved_answers':None,
            'state': '{}'
        }
        state_2 = {
            'answer_id': 'answer_id',
            'question': 'question_text\n',
            'answer': 'correct_answer_text',
            'correct_answer': 'correct_answer_text',
            'username': self.student.username,
            'email': self.student.email,
            'user_rut': '',
            'attempts': '1',
            'gained': '1.0',
            'possible': '1.0',
            'total': '3',
            'has_saved_answers': True,
            'state': '{}'
        }
        report.return_value = [state_1, state_2]
        from lms.djangoapps.courseware.models import StudentModule
        data = {'format': False, 'course': str(self.course.id), 'base_url':'this_is_a_url'}
        task_input = {'data': data }
        module = StudentModule(
            module_state_key=self.items[0].location,
            student=self.student,
            course_id=self.course.id,
            module_type='problem',
            state='{"score": {"raw_earned": 1, "raw_possible": 3}, "seed": 1, "attempts": 1}')
        module.save()
        with patch('lms.djangoapps.instructor_task.tasks_helper.runner._get_current_task'):
            result = generate(
                None, None, self.course.id,
                task_input, 'EOL_Xblock_Completion'
            )
        report_store = ReportStore.from_config(config_name='GRADES_DOWNLOAD')
        header_row = ";".join(['"Username"', '"Email"', '"Run"', '"Seccion"', '"SubSeccion"', '"Unidad"', '"Titulo"', '"Pregunta"', '"Respuesta Estudiante"', '"Resp. Correcta"', '"Intentos"', '"Pts Ganados"', '"Pts Posibles"', '"Pts Total Componente"', '"block id"', '"Has saved answers"'])
        base_student_row = ";".join([           
            '"{}"'.format(self.student.username),
            '"{}"'.format(self.student.email),
            '""',
            '"{}"'.format(self.chapter.display_name),
            '"{}"'.format(self.section.display_name),
            '"{}"'.format( self.subsection.display_name),
             '"{}"'.format(self.items[0].display_name),
        ])
        student_row = base_student_row + ';"question_text";"answer_text";"correct_answer_text";"1";"0";"1.0";"3"'
        student_row2 = base_student_row + ';"question_text";"correct_answer_text";"correct_answer_text";"1";"1.0";"1.0";"3";"'+str(self.items[0].location)+'";"has_saved_answers"'
        expected_data = [header_row, student_row, student_row2, student_row]
        self._verify_csv_file_report(report_store, expected_data)

    @patch("xblockcompletion.views.XblockCompletionView.generate_report_data")
    def test_xblockcompletion_get_all_data_no_responses(self, report):
        """
            Test xblockcompletion view all data when xblock dont have responses yet
        """
        generated_report_data = {}               
        report.return_value = generated_report_data
        data = {'format': False, 'course': str(self.course.id), 'base_url':'this_is_a_url'}
        task_input = {'data': data }
        with patch('lms.djangoapps.instructor_task.tasks_helper.runner._get_current_task'):
            result = generate(
                None, None, self.course.id,
                task_input, 'EOL_Xblock_Completion'
            )
        report_store = ReportStore.from_config(config_name='GRADES_DOWNLOAD')
        header_row = ";".join(['"Username"', '"Email"', '"Run"', '"Seccion"', '"SubSeccion"', '"Unidad"', '"Titulo"', '"Pregunta"', '"Respuesta Estudiante"', '"Resp. Correcta"', '"Intentos"', '"Pts Ganados"', '"Pts Posibles"', '"Pts Total Componente"', '"block id"', '"Has saved answers"'])
        base_student_row = ";".join([
            self.items[0].display_name,
            self.student.username,
            self.student.email,
            '',
            self.chapter.display_name,
            self.section.display_name,
            self.subsection.display_name
        ])
        report_csv_filename = report_store.links_for(self.course.id)[0][0]
        report_path = report_store.path_to(self.course.id, report_csv_filename)
        with report_store.storage.open(report_path) as csv_file:
            csv_file_data = csv_file.read()
            # Removing unicode signature (BOM) from the beginning
            csv_file_data = csv_file_data.decode("utf-8-sig")
            self.assertIn(header_row, csv_file_data)
            self.assertFalse(base_student_row in csv_file_data)
    
    def test_xblockcompletion_no_data_format(self):
        """
            Test xblockcompletion view when no exitst format
        """
        from lms.djangoapps.courseware.models import StudentModule
        data = {
            'course': str(self.course.id)
        }
        response = self.client_instructor.get(reverse('xblockcompletion-data:data'), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response._container[0].decode()), {'error': 'Falta parametro format o parametro incorrecto'})

    def test_xblockcompletion_no_data_course(self):
        """
            Test xblockcompletion view no exitst course params
        """
        from lms.djangoapps.courseware.models import StudentModule
        data = {
            'format':'all'
        }
        response = self.client_instructor.get(reverse('xblockcompletion-data:data'), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response._container[0].decode()), {'error': 'Falta parametro course o parametro incorrecto'})

    def test_xblockcompletion_course_no_exists(self):
        """
            Test xblockcompletion view when course_no_exists
        """
        from lms.djangoapps.courseware.models import StudentModule
        data = {
            'format':'all',
            'course': 'course-v1:eol+test101+2020'
        }
        response = self.client_instructor.get(reverse('xblockcompletion-data:data'), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response._container[0].decode()), {'error': 'Falta parametro course o parametro incorrecto'})

    def test_xblockcompletion_get_user_is_anonymous(self):
        """
            Test xblockcompletion view when user is anonymous
        """
        client = Client()
        response = self.client.get(reverse('xblockcompletion-data:data'))
        request = response.request
        self.assertEqual(response.status_code, 404)

    def test_xblockcompletion_get_user_no_permission(self):
        """
            Test xblockcompletion view when user is a student
        """
        data = {
            'format':'all',
            'course':  str(self.course.id)
        }
        response = self.client_student.get(reverse('xblockcompletion-data:data'), data)
        request = response.request
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response._container[0].decode()), {'error': 'Usuario no tiene rol para esta funcionalidad'})

    def test_xblockcompletion_get_data_researcher(self):
        """
            Test xblockcompletion view when user is data researcher
        """
        data = {
            'format':'resumen',
            'course':  str(self.course.id)
        }
        response = self.client_data_researcher.get(reverse('xblockcompletion-data:data'), data)
        request = response.request
        r = json.loads(response._container[0].decode())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(r['status'], 'El reporte de preguntas esta siendo creado, en un momento estará disponible para descargar.')