import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth import get_user_model
from ai_modules.views import ai_list

User = get_user_model()
user = User.objects.get(username='representante.utp')

factory = RequestFactory()
request = factory.get('/')
request.user = user

try:
    response = ai_list(request)
    print("STATUS CODE:", response.status_code)
    try:
        print("URL:", response.url)
    except:
        pass
except Exception as e:
    import traceback
    traceback.print_exc()

