#!/usr/bin/env python3
"""Programmatically create a Django superuser (non-interactive)."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartspend.settings')
django.setup()

from core.models import User

EMAIL = 'admin@smartspend.local'
PASSWORD = 'Admin123!'
FIRST = 'Admin'
LAST = 'User'

if not User.objects.filter(email__iexact=EMAIL).exists():
    user = User.objects.create_superuser(
        email=EMAIL,
        password=PASSWORD,
        first_name=FIRST,
        last_name=LAST,
    )
    print(f'✅  Superuser CREATED:')
    print(f'     Email   : {EMAIL}')
    print(f'     Password: {PASSWORD}')
    print(f'     UUID    : {user.user_id}')
    print(f'\n    Login at: http://127.0.0.1:8000/admin/')
else:
    user = User.objects.get(email__iexact=EMAIL)
    user.set_password(PASSWORD)
    user.is_staff = True
    user.is_superuser = True
    user.first_name = FIRST
    user.last_name = LAST
    user.save()
    print(f'✅  Superuser UPDATED (password reset):')
    print(f'     Email   : {EMAIL}')
    print(f'     Password: {PASSWORD}')
    print(f'\n    Login at: http://127.0.0.1:8000/admin/')
