#!/bin/dash
pip install -e git+https://github.com/eol-uchile/uchileedxlogin@362009d0b393b52d852c6aa1c62c4d51abe01bae#egg=uchileedxlogin
pip install -e /openedx/requirements/eol_xblock_completion

cd /openedx/requirements/eol_xblock_completion
cp /openedx/edx-platform/setup.cfg .
mkdir test_root
cd test_root/
ln -s /openedx/staticfiles .

cd /openedx/requirements/eol_xblock_completion

DJANGO_SETTINGS_MODULE=lms.envs.test EDXAPP_TEST_MONGO_HOST=mongodb pytest xblockcompletion/tests.py
