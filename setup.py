from distutils.core import setup

setup(
    name='django-squeezemail',
    version='0.1.1',
    author='Brandon Jurewicz',
    author_email='brandonjur@gmail.com',
    packages=['squeezemail'],
    url='http://pypi.python.org/pypi/django-squeezemail/',
    license='LICENSE',
    description='Django email drip/autoresponder',
    long_description=open('README.rst').read(),
    install_requires=[
        "Django >= 1.7.1",
        "feincms >= 1.11",
        "django-timedeltafield >= 0.7.10",
        "django-tinymce >= 2.3.0",
        "celery >= 3.1.22",
        "python-memcached >= 1.57",
    ],
)