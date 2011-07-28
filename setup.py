from setuptools import setup, find_packages

setup(
    name='NotifServer',
    version=0.8,
    packages=find_packages(),

    install_requires=[
        'nose',
        'PasteDeploy',
        'PasteScript',
        'pika',
        'webob',
        'webtest',
    ],

    entry_points="""
        [paste.app_factory]
        client_agent = notifserver.clientagent:make_client_agent
        post_office = notifserver.postoffice:make_post_office
        post_office_router = notifserver.postoffice:make_post_office_router
        smtp_interface = notifserver.smtp_interface:make_smtp_interface
        [paste.filter_app_factory]
        basic_auth = notifserver.auth:make_basic_auth
    """,

    test_suite = 'nose.collector',

    author="Shane da Silva",
    author_email="sdasilva@mozilla.com",
    description="Push notification server",
    keywords="push notifications server real-time messaging",
)
