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
from student.tests.factories import CourseEnrollmentAllowedFactory, UserFactory, CourseEnrollmentFactory
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from student.roles import CourseInstructorRole, CourseStaffRole
from .views import XblockCompletionView
from .utils import get_data_course
from rest_framework_jwt.settings import api_settings
from django.test.utils import override_settings
from django.utils.translation import gettext as _
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
        with patch('student.models.cc.User.save'):
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
                user=self.student, course_id=self.course.id)
            self.client_student.login(
                username='student', password='test')
    
    def test_xblockcompletion_get(self):
        """
            Test xblockcompletion view
        """
        response = self.client_instructor.get(reverse('xblockcompletion-data:data'))
        request = response.request
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request['PATH_INFO'], '/xblockcompletion/data')
    
    def test_xblockcompletion_get_data_course(self):
        """
            Test xblockcompletion get_data_course
        """
        #Diff is 8444 characters long. Set self.maxDiff to None to see it.
        course_structure = {
                    'has_children': True, 
                    'display_name': '2021', 
                    'id': 'i4x://mss/999/course/2021', 
                    'child_info': {
                        'display_name': 'Section', 
                        'category': 'chapter', 
                        'children': [{
                            'has_children': True, 
                            'display_name': self.chapter.display_name, 
                            'id': str(self.chapter.location), 
                            'child_info': {
                                'display_name': 'Subsection', 
                                'category': 'sequential',
                                'children': [{
                                    'has_children': True, 
                                    'display_name': self.section.display_name, 
                                    'id': str(self.section.location), 
                                    'child_info': {
                                        'display_name': 'Unit', 
                                        'category': 'vertical', 
                                        'children': [{
                                            'has_children': True, 
                                            'display_name': self.subsection.display_name, 
                                            'id': str(self.subsection.location), 
                                            'child_info': {
                                                'children': [{
                                                    'has_children': False, 
                                                    'display_name': self.items[0].display_name, 
                                                    'id': str(self.items[0].location), 
                                                    'category': 'problem'
                                                    }, 
                                                    {'has_children': False, 
                                                    'display_name': self.items[1].display_name, 
                                                    'id': str(self.items[1].location), 
                                                    'category': 'problem'
                                                    }, 
                                                    {'has_children': False,
                                                    'display_name': self.items[2].display_name, 
                                                    'id': str(self.items[2].location), 
                                                    'category': 'problem'
                                                    }]
                                            }, 
                                            'category': 'vertical'
                                            }]
                                    }, 
                                    'category': 'sequential'}]
                            }, 
                            'category': 'chapter'
                            }]
                        }, 
                    'category': 'course'}
        response = get_data_course(str(self.course.id))
        self.assertEqual(response, course_structure)

    def test_xblockcompletion_get_resumen(self):
        """
            Test xblockcompletion view resumen data
        """
        from lms.djangoapps.courseware.models import StudentModule
        data = {
            'format':'resumen',
            'course': str(self.course.id)
        }
        module = StudentModule(
            module_state_key=self.items[0].location,
            student=self.student,
            course_id=self.course.id,
            module_type='problem',
            state='{"score": {"raw_earned": 0, "raw_possible": 3}, "seed": 1}')
        module.save()
        response = self.client_instructor.get(reverse('xblockcompletion-data:data'), data)
        self.assertEqual(response.status_code, 200)
        content = [x.decode() for x in response._container]
        self.assertEqual(content[1], 'Titulo;block_id;Username;Email;Run;Seccion;SubSeccion;Unidad;Intentos;Pts Ganados;Pts Posibles;State\r\n')
        aux_response = self.items[0].display_name + ';' + str(self.items[0].location)+ ';' + self.student.username + ';' + self.student.email+ ';;1.' + self.chapter.display_name+ ';' + '1.1.' + self.section.display_name+ ';1.1.1.' + self.subsection.display_name + ';0;0;3;'
        self.assertTrue(aux_response in content[2])
    
    @patch("xblockcompletion.views.XblockCompletionView.get_report_xblock")
    def test_xblockcompletion_get_all_data(self, report):
        """
            Test xblockcompletion view all data
        """
        state_1 = {_("Answer ID"): 'answer_id',
            _("Question"): 'question_text',
            _("Answer"): 'answer_text',
            _("Correct Answer") : 'correct_answer_text'
            }
        state_2 = {_("Answer ID"): 'answer_id',
            _("Question"): 'question_text',
            _("Answer"): 'correct_answer_text',
            _("Correct Answer") : 'correct_answer_text'
            }
        generated_report_data = {self.student.username : [state_1,state_2,state_1]}               
        report.return_value = generated_report_data
        from lms.djangoapps.courseware.models import StudentModule
        data = {
            'format':'all',
            'course': str(self.course.id)
        }
        module = StudentModule(
            module_state_key=self.items[0].location,
            student=self.student,
            course_id=self.course.id,
            module_type='problem',
            state='{"score": {"raw_earned": 1, "raw_possible": 3}, "seed": 1, "attempts": 1}')
        module.save()
        response = self.client_instructor.get(reverse('xblockcompletion-data:data'), data)
        self.assertEqual(response.status_code, 200)
        content = [x.decode() for x in response._container]
        self.assertEqual(content[1], 'Titulo;block_id;Username;Email;Run;Seccion;SubSeccion;Unidad;Pregunta;Respuesta Estudiante;Resp. Correcta;Intentos;Pts Ganados;Pts Posibles;Pts Total Componente\r\n')
        aux_response = self.items[0].display_name + ';' + str(self.items[0].location)+ ';' + self.student.username + ';' + self.student.email+ ';;1.' + self.chapter.display_name+ ';' + '1.1.' + self.section.display_name+ ';1.1.1.' + self.subsection.display_name
        aux_response_1 = aux_response + ';question_text;answer_text;correct_answer_text;1;0;1.0;3\r\n'
        aux_response_2 = aux_response + ';question_text;correct_answer_text;correct_answer_text;1;1.0;1.0;3\r\n'
        self.assertEqual(aux_response_1, content[2])
        self.assertEqual(aux_response_2, content[3])
        self.assertEqual(aux_response_1, content[4])

    @patch("xblockcompletion.views.XblockCompletionView.get_report_xblock")
    def test_xblockcompletion_get_all_data_no_responses(self, report):
        """
            Test xblockcompletion view all data when xblock dont have responses yet
        """
        report.return_value = {}
        from lms.djangoapps.courseware.models import StudentModule
        data = {
            'format':'all',
            'course': str(self.course.id)
        }
        module = StudentModule(
            module_state_key=self.items[0].location,
            student=self.student,
            course_id=self.course.id,
            module_type='problem',
            state='{"score": {"raw_earned": 0, "raw_possible": 3}, "seed": 1, "attempts": 0}')
        module.save()
        response = self.client_instructor.get(reverse('xblockcompletion-data:data'), data)
        self.assertEqual(response.status_code, 200)
        content = [x.decode() for x in response._container]
        self.assertEqual(content[1], 'Titulo;block_id;Username;Email;Run;Seccion;SubSeccion;Unidad;Pregunta;Respuesta Estudiante;Resp. Correcta;Intentos;Pts Ganados;Pts Posibles;Pts Total Componente\r\n')
        aux_response = self.items[0].display_name + ';' + str(self.items[0].location)+ ';' + self.student.username + ';' + self.student.email+ ';;1.' + self.chapter.display_name+ ';' + '1.1.' + self.section.display_name+ ';1.1.1.' + self.subsection.display_name
        aux_response_1 = aux_response + ';;;;0;0;3;3\r\n'
        self.assertEqual(aux_response_1, content[2])
    
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