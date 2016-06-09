import json

import peewee

from ban.commands import command, reporter
from ban.core.models import Municipality, HouseNumber, Group, Position, PostCode
from ban.utils import compute_cia

from . import helpers

__namespace__ = 'import'


@command
@helpers.nodiff
def init(path, limit=0, **kwargs):
    """Initial import for real™."""
    rows = helpers.iter_file(path, formatter=json.loads)
    if limit:
        print('Running with limit', limit)
        extract = []
        for i, row in enumerate(rows):
            if i >= limit:
                break
            extract.append(row)
        rows = extract
        total = limit
    else:
        print('Computing file size')
        total = sum(1 for line in helpers.iter_file(path))
        print('Done computing file size')
    helpers.batch(process_row, rows, chunksize=100, total=total)


@helpers.session
def process_row(row):
    kind = row.pop('type')
    if not kind:
        return reporter.error('Missing "type" key', row)
    if kind == "municipality":
        return process_municipality(row)
    elif kind == "group":
        return process_group(row)
    elif kind == "postcode":
        return process_postcode(row)
    elif kind == "housenumber":
        return process_housenumber(row)
    elif kind == "position":
        return process_position(row)


def process_municipality(row):
    row['attributes'] = {'source': row.pop('source')}
    row['siren'] = '2101' + row['insee']  # Dummy, but hey.
    validator = Municipality.validator(**row)
    if validator.errors:
        return reporter.error('Municipality errors', validator.errors)
    validator.save()
    reporter.notice('Imported Municipality', row['insee'])


def process_group(row):
    municipality = 'insee:{}'.format(row.get('municipality:insee'))
    fantoir = row.get('group:fantoir')
    fantoir = '{}{}'.format(fantoir[:5], fantoir[6:10])
    name = row.get('name')
    kind = row.get('group')
    source = row.get('source')
    attributes = {'source': source}
    data = dict(name=name, fantoir=fantoir, municipality=municipality,
                kind=kind, version=1, attributes=attributes)
    update = False
    try:
        instance = Group.coerce('fantoir:{}'.format(fantoir))
    except Group.DoesNotExist:
        instance = None
    else:
        if instance.attributes['source'] == source:
            # Reimporting same data?
            reporter.warning('Group already exist', instance.id)
            return
        data['version'] = instance.version + 1
        update = True
    validator = Group.validator(instance=instance, update=update, **data)
    if validator.errors:
        reporter.error('Invalid group data', validator.errors)
    else:
        group = validator.save()
        reporter.notice('Created group', group.id)


def process_postcode(row):
    municipality = 'insee:{}'.format(row.get('municipality:insee'))
    # TODO: add attributes to PostCode.
    # attributes = {'source': row.pop('source')}
    name = row.get('name')
    code = row.get('postcode')
    data = dict(name=name, code=code, municipality=municipality,
                version=1)
    instance = PostCode.first(PostCode.code == code, PostCode.name == name)
    if instance:
        return reporter.notice('PostCode already exists', code)
    validator = PostCode.validator(**data)
    if validator.errors:
        return reporter.error('PostCode errors', validator.errors)
    validator.save()
    reporter.notice('Imported PostCode', code)


def process_housenumber(row):
    number = row.get('numero')
    ordinal = row.get('ordinal') or None
    raw_fantoir = row.get('group:fantoir')
    insee = raw_fantoir[:5]
    fantoir = '{}{}'.format(raw_fantoir[:5], raw_fantoir[6:10])
    cia = compute_cia(insee, raw_fantoir[6:10], number, ordinal)
    parent = 'fantoir:{}'.format(fantoir)
    source = row.get('source')
    # TODO add attributes to HouseNumber
    # attributes = {'source': source}
    data = dict(number=number, ordinal=ordinal, version=1, parent=parent)
    instance = HouseNumber.first(HouseNumber.cia == cia)
    update = False
    if instance:
        # if instance.attributes['source'] == source:
        #     # Reimporting same data?
        #     reporter.warning('HouseNumber already exists', instance.id)
        #     return
        data['version'] = instance.version + 1
        update = True

    validator = HouseNumber.validator(instance=instance, update=update, **data)
    if validator.errors:
        reporter.error('HouseNumber errors', (validator.errors, parent))
    else:
        validator.save()
        msg = 'HouseNumber Updated' if instance else 'HouseNumber created'
        reporter.notice(msg, (number, ordinal, parent))


def process_position(row):
    kind = row.get("kind")
    source = row.get("source")
    cia = row.get('housenumber:cia')
    cia = cia[:10] + cia[11:]  # Remove control letter from data instead.
    center = row.get('geometry')
    housenumber = HouseNumber.first(HouseNumber.cia == cia)
    if not housenumber:
        reporter.error('Position housenumber does not exist', cia)
        return
    instance = Position.first(Position.housenumber == housenumber,
                              Position.kind == kind, Position.source == source)
    version = instance.version + 1 if instance else 1
    data = dict(kind=kind, source=source, housenumber=housenumber,
                center=center, positioning=Position.OTHER, version=version)
    validator = Position.validator(instance=instance, **data)
    if validator.errors:
        reporter.error('Position error', validator.errors)
    else:
        position = validator.save()
        msg = 'Position updated' if instance else 'Position created'
        reporter.notice(msg, position.id)
