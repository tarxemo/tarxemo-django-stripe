import sys
import django
from django.conf import settings
from django.core.management import call_command

if not settings.configured:
    settings.configure(
        DEBUG=True,
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        },
        INSTALLED_APPS=[
            'django.contrib.contenttypes',
            'django.contrib.auth',
            'stripe_payments',
        ],
    )
    django.setup()

call_command('makemigrations', 'stripe_payments')
