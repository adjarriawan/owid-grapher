import json
import subprocess
import hashlib
from django.db import models
from django.db.models import Q


class PasswordReset(models.Model):
    class Meta:
        db_table = "password_resets"

    email = models.CharField(max_length=255)
    token = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)


class User(models.Model):
    class Meta:
        db_table = "users"

    name = models.CharField(max_length=255, unique=True)
    email = models.CharField(max_length=255, unique=True)
    password = models.CharField(max_length=60)
    remember_token = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Chart(models.Model):
    class Meta:
        db_table = "charts"
        unique_together = (('slug', 'published'),)

    name = models.CharField(max_length=255)
    config = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_edited_by = models.ForeignKey(User, to_field='name', on_delete=models.DO_NOTHING, blank=True, null=True,
                                       db_column='last_edited_by')
    last_edited_at = models.DateTimeField(auto_now=True)  # clarify the use of this one
    origin_url = models.CharField(max_length=255)
    notes = models.TextField()
    slug = models.CharField(max_length=255, blank=True, null=True)
    published = models.BooleanField(default=False)
    starred = models.BooleanField(default=False)
    type = models.CharField(max_length=255, choices=(('LineChart', 'Line chart'), ('ScatterPlot', 'Scatter plot'),
                                                     ('StackedArea', 'Stacked area'), ('MultiBar', 'Multi bar'),
                                                     ('HorizontalMultiBar', 'Horizontal Multi bar'),
                                                     ('DiscreteBar', 'Discrete bar'),
                                                     ('SlopeChart', 'Slope chart')), blank=True, null=True)

    @classmethod
    def owid_commit(cls):
        """
        :return: Will return latest commit revision for the repo
        """
        git_commit = subprocess.run('git rev-parse HEAD', stdout=subprocess.PIPE, shell=True).stdout
        return str(git_commit)

    def make_cache_tag(self):
        """
        :return: A cache tag we can send along to the client. This uniquely identifies a particular
        combination of dataset variables, and is sent along to servevariables view when the chart requests
        all of its data. Allows us to reduce chart loading times by caching most of the data in
        Cloudflare or the browser.
        """
        variable_cache_tag = str(self.updated_at) + ' + ' + Chart.owid_commit()
        config = json.loads(self.config)
        dims = config['chart-dimensions']
        varids = [int(d['variableId']) for d in dims if 'variableId' in d]
        vartimestamps = Variable.objects.filter(pk__in=varids)
        updated_at_list = []
        for each in vartimestamps:
            updated_at_list.append(str(each.updated_at))
        variable_cache_tag += ' + '.join(updated_at_list)
        m = hashlib.md5()
        m.update(variable_cache_tag.encode(encoding='utf-8'))
        variable_cache_tag = m.hexdigest()
        return variable_cache_tag


    @classmethod
    def get_config_with_url(cls, chart):
        """
        :param chart: Chart object
        :return: A Chart's config dictionary
        """
        config = json.loads(chart.config)
        config['id'] = chart.pk
        config['title'] = chart.name
        config['chart-type'] = chart.type
        config['internalNotes'] = chart.notes
        config['slug'] = chart.slug
        config['data-entry-url'] = chart.origin_url
        config['published'] = chart.published
        logos = []
        for each in list(Logo.objects.filter(name__in=config['logos'])):
            logos.append(each.svg)
        config['logosSVG'] = logos
        return config

    @classmethod
    def find_with_redirects(cls, slug):
        """
        :param slug: Slug for the requested Chart
        :return: Chart object
        """
        try:
            intslug = int(slug)
        except ValueError:
            intslug = None
        try:
            chart = Chart.objects.get((Q(slug=slug) | Q(pk=intslug)), published__isnull=False)
        except Chart.DoesNotExist:
            try:
                redirect = ChartSlugRedirect.objects.get(slug=slug)
            except ChartSlugRedirect.DoesNotExist:
                return False
            chart = Chart.objects.get(pk=redirect.chart_id, published__isnull=False)
        return chart


class DatasetCategory(models.Model):
    class Meta:
        db_table = "dataset_categories"

    name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class DatasetSubcategory(models.Model):
    class Meta:
        db_table = "dataset_subcategories"
        unique_together = (('name', 'fk_dst_cat_id'),)

    name = models.CharField(max_length=255)
    fk_dst_cat_id = models.ForeignKey(DatasetCategory, blank=True, null=True, on_delete=models.DO_NOTHING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Dataset(models.Model):
    class Meta:
        db_table = "datasets"
        unique_together = (('name', 'namespace'),)

    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    fk_dst_cat_id = models.ForeignKey(DatasetCategory, blank=True, null=True, on_delete=models.DO_NOTHING)
    fk_dst_subcat_id = models.ForeignKey(DatasetSubcategory, blank=True, null=True, on_delete=models.DO_NOTHING)
    namespace = models.CharField(max_length=255, default='owid')


class Source(models.Model):
    class Meta:
        db_table = 'sources'
        unique_together = (('name', 'datasetid'),)

    name = models.CharField(max_length=255)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    datasetid = models.ForeignKey(Dataset, db_column='datasetId', blank=True, null=True, on_delete=models.DO_NOTHING)


class VariableType(models.Model):
    class Meta:
        db_table = 'variable_types'

    name = models.CharField(max_length=255)
    issortable = models.BooleanField(db_column='isSortable', default=False)


class Variable(models.Model):
    class Meta:
        db_table = 'variables'
        unique_together = (('code', 'fk_dst_id'), ('name', 'fk_dst_id'),)

    name = models.CharField(max_length=255)
    unit = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    fk_dst_id = models.ForeignKey(Dataset, on_delete=models.CASCADE)
    sourceid = models.ForeignKey(Source, on_delete=models.DO_NOTHING, db_column='sourceId')
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    fk_var_type_id = models.ForeignKey(VariableType, on_delete=models.DO_NOTHING)
    uploaded_by = models.ForeignKey(User, to_field='name', on_delete=models.DO_NOTHING, db_column='uploaded_by', blank=True, null=True)
    uploaded_at = models.DateTimeField()
    code = models.CharField(max_length=255, blank=True, null=True)
    coverage = models.CharField(max_length=255)
    timespan = models.CharField(max_length=255)


class ChartDimension(models.Model):
    class Meta:
        db_table = "chart_dimensions"

    chartid = models.ForeignKey(Chart, on_delete=models.CASCADE, db_column='chartId')
    order = models.IntegerField()
    variableid = models.ForeignKey(Variable, models.DO_NOTHING, db_column='variableId')
    property = models.CharField(max_length=255)
    unit = models.CharField(max_length=255)
    displayname = models.CharField(max_length=255, db_column='displayName')
    targetyear = models.IntegerField(db_column='targetYear', blank=True, null=True)
    tolerance = models.IntegerField(blank=True, default=5)
    color = models.CharField(max_length=255)


class ChartSlugRedirect(models.Model):
    class Meta:
        db_table = 'chart_slug_redirects'

    slug = models.CharField(unique=True, max_length=255)
    chart_id = models.IntegerField()


class Entity(models.Model):
    class Meta:
        db_table = "entities"

    code = models.CharField(max_length=255, blank=True, null=True, unique=True)
    name = models.CharField(max_length=255, unique=True)
    validated = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    displayname = models.CharField(db_column='displayName', max_length=255)


class DataValue(models.Model):
    class Meta:
        db_table = "data_values"
        unique_together = (('fk_ent_id', 'fk_var_id', 'year'),)

    value = models.CharField(max_length=255)
    fk_ent_id = models.ForeignKey(Entity, blank=True, null=True, on_delete=models.DO_NOTHING)
    fk_var_id = models.ForeignKey(Variable, on_delete=models.CASCADE)
    year = models.IntegerField()


class InputFile(models.Model):
    class Meta:
        db_table = 'input_files'

    raw_data = models.TextField()
    fk_user_id = models.ForeignKey(User, on_delete=models.DO_NOTHING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class License(models.Model):
    class Meta:
        db_table = 'licenses'

    name = models.CharField(max_length=255)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Logo(models.Model):
    class Meta:
        db_table = 'logos'

    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    svg = models.TextField()


class Setting(models.Model):
    class Meta:
        db_table = 'settings'

    meta_name = models.CharField(max_length=255)
    meta_value = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class UserInvitation(models.Model):
    class Meta:
        db_table = 'user_invitations'

    code = models.CharField(max_length=255)
    email = models.CharField(max_length=255)
    user_id = models.ForeignKey(User, on_delete=models.DO_NOTHING)
    status = models.CharField(max_length=10, choices=(('pending', 'pending'), ('successful', 'successful'),
                                                      ('canceled', 'canceled'), ('expired', 'expired')))
    valid_till = models.DateTimeField()
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
