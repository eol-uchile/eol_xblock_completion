import xblockcompletion
import os

def plugin_settings(settings):
    settings.XBLOCKCOMPLETION_LIMIT_STUDENTS = 1000
    template_path = os.path.join(os.path.dirname(xblockcompletion.__file__), "templates")

    # Add app template path to the base list, so its included on mako lookups
    if hasattr(settings, 'MAKO_TEMPLATE_DIRS_BASE'):
        settings.MAKO_TEMPLATE_DIRS_BASE.append(template_path)
