# Generated by Django 2.2.5 on 2020-02-06 12:03

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('resources', '0112_resource_configuration'),
    ]

    operations = [
        migrations.AlterField(
            model_name='accessibilityvalue',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Lisäysaika'),
        ),
        migrations.AlterField(
            model_name='accessibilityvalue',
            name='modified_at',
            field=models.DateTimeField(auto_now=True, verbose_name='Muokkausaika'),
        ),
        migrations.AlterField(
            model_name='accessibilityviewpoint',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Lisäysaika'),
        ),
        migrations.AlterField(
            model_name='accessibilityviewpoint',
            name='modified_at',
            field=models.DateTimeField(auto_now=True, verbose_name='Muokkausaika'),
        ),
        migrations.AlterField(
            model_name='accessibilityviewpoint',
            name='name',
            field=models.CharField(max_length=200, verbose_name='Nimi'),
        ),
        migrations.AlterField(
            model_name='accessibilityviewpoint',
            name='name_en',
            field=models.CharField(max_length=200, null=True, verbose_name='Nimi'),
        ),
        migrations.AlterField(
            model_name='accessibilityviewpoint',
            name='name_fi',
            field=models.CharField(max_length=200, null=True, verbose_name='Nimi'),
        ),
        migrations.AlterField(
            model_name='accessibilityviewpoint',
            name='name_sv',
            field=models.CharField(max_length=200, null=True, verbose_name='Nimi'),
        ),
        migrations.AlterField(
            model_name='accessibilityviewpoint',
            name='order_text',
            field=models.CharField(default='0', max_length=200, verbose_name='Tilaus'),
        ),
        migrations.AlterField(
            model_name='resourceaccessibility',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Lisäysaika'),
        ),
        migrations.AlterField(
            model_name='resourceaccessibility',
            name='modified_at',
            field=models.DateTimeField(auto_now=True, verbose_name='Muokkausaika'),
        ),
        migrations.AlterField(
            model_name='resourceaccessibility',
            name='resource',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='accessibility_summaries', to='resources.Resource', verbose_name='Resurssi'),
        ),
        migrations.AlterField(
            model_name='unitaccessibility',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Lisäysaika'),
        ),
        migrations.AlterField(
            model_name='unitaccessibility',
            name='modified_at',
            field=models.DateTimeField(auto_now=True, verbose_name='Muokkausaika'),
        ),
        migrations.AlterField(
            model_name='unitaccessibility',
            name='unit',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='accessibility_summaries', to='resources.Unit', verbose_name='Resurssi'),
        ),
    ]
