from django.db import migrations


DEFAULT_ITEMS = [
    ("", "होम", "home"),
    ("", "परिचय", "about"),
    ("", "प्रचार-प्रसार", "prachar"),
    ("", "अनमोल लेख", "articles"),
    ("महापुरुष परिचय", "श्रद्धेय श्रीजयदयालजी गोयन्दका", "about"),
    ("महापुरुष परिचय", "श्रद्धेय श्रीहनुमानप्रसादजी पोद्दार", "about"),
    ("महापुरुष परिचय", "श्रद्धेय स्वामी श्रीरामसुखदासजी महाराज", "about"),
    ("सहायता और समर्थन", "ऐप भाषा", "account"),
    ("सहायता और समर्थन", "संपर्क करें", "contact"),
    ("सहायता और समर्थन", "फॉलो करें", "follow"),
]


def remove_default_side_menu_items(apps, schema_editor):
    SideMenuItem = apps.get_model("library", "SideMenuItem")
    for section, title, action in DEFAULT_ITEMS:
        SideMenuItem.objects.filter(section=section, title=title, action=action).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0011_subject_book_subjects"),
    ]

    operations = [
        migrations.RunPython(remove_default_side_menu_items, migrations.RunPython.noop),
    ]
