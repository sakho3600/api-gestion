import re
from urllib.parse import urlencode

import falcon

from ban.core import models

from .wsgi import app


__all__ = ['Municipality', 'Street', 'Locality', 'Housenumber', 'Position']


class WithURL(type):

    urls = []

    def __new__(mcs, name, bases, attrs, **kwargs):
        cls = super().__new__(mcs, name, bases, attrs)
        if hasattr(cls, 'model'):
            for route in cls.routes():
                app.add_route(route, cls())
        return cls


class URLMixin(object, metaclass=WithURL):

    @classmethod
    def base_url(cls):
        return "/" + re.sub("([a-z])([A-Z])", "\g<1>/\g<2>", cls.__name__).lower()

    @classmethod
    def url_name(cls):
        return re.sub("([a-z])([A-Z])", "\g<1>-\g<2>", cls.__name__).lower()

    @classmethod
    def url_path(cls):
        return cls.base_url()


class BaseCRUD(URLMixin):
    identifiers = []
    DEFAULT_LIMIT = 20
    MAX_LIMIT = 100

    def not_found(self, msg='Not found'):
        return self.error(404, msg)

    def error(self, status=400, msg='Invalid request'):
        return self.json(status, error=msg)

    @classmethod
    def routes(cls):
        return [
            cls.base_url(),
            # cls.base_url() + '/{id}',
            cls.base_url() + '/{identifier}:{id}',
            cls.base_url() + '/{identifier}:{id}/{route}',
            cls.base_url() + '/{identifier}:{id}/{route}/{route_id}',
        ]
        # return cls.base_url() + r'(?:(?P<key>[\w_]+)/(?P<ref>[\w_]+)/(?:(?P<route>[\w_]+)/(?:(?P<route_id>[\d]+)/)?)?)?$'  # noqa

    def get_object(self, identifier, id, **kwargs):
        try:
            return self.model.get(getattr(self.model, identifier) == id)
        except self.model.DoesNotExist:
            raise falcon.HTTPNotFound()

    def on_get(self, req, resp, **kwargs):
        identifier = kwargs.get('identifier')
        if identifier and identifier not in self.identifiers + ['id']:
            msg = 'Invalid identifier: {}'.format(identifier)
            raise falcon.HTTPBadRequest(msg, msg)
        instance = self.get_object(**kwargs)
        if 'route' in kwargs:
            name = 'on_get_{}'.format(kwargs['route'])
            view = getattr(self, name, None)
            if view and callable(view):
                return view(req, resp, **kwargs)
            else:
                raise falcon.HTTPBadRequest('Invalid route', 'Invalid route')
        resp.json(**instance.as_resource)

    def on_post(self, req, resp, *args, **kwargs):
        if 'id' in kwargs:
            instance = self.get_object(**kwargs)
        else:
            instance = None
        self.save_object(req.params, req, resp, instance, **kwargs)

    def on_put(self, req, resp, *args, **kwargs):
        instance = self.get_object(**kwargs)
        data = req.json
        self.save_object(data, req, resp, instance, **kwargs)

    def save_object(self, data, req, resp, instance=None, **kwargs):
        validator = self.model.validator(**data)
        if not validator.errors:
            try:
                instance = validator.save(instance=instance)
            except instance.ForcedVersionError:
                status = 409
                # Return original object.
                instance = self.get_object(**kwargs)
            else:
                status = 200 if 'id' in kwargs else 201
            resp.status = str(status)
            resp.json(**instance.as_resource)
        else:
            resp.status = str(422)
            resp.json(errors=validator.errors)

    def get_limit(self, req):
        return min(int(req.params.get('limit', self.DEFAULT_LIMIT)),
                   self.MAX_LIMIT)

    def get_offset(self, req):
        try:
            return int(req.params.get('offset'))
        except (ValueError, TypeError):
            return 0

    def collection(self, req, resp, queryset):
        limit = self.get_limit(req)
        offset = self.get_offset(req)
        end = offset + limit
        count = queryset.count()
        kwargs = {
            'collection': list(queryset[offset:end]),
            'total': count,
        }
        url = '{}://{}{}'.format(req.protocol, req.host, req.path)
        if count > end:
            kwargs['next'] = '{}?{}'.format(url, urlencode({'offset': end}))
        if offset >= limit:
            kwargs['previous'] = '{}?{}'.format(url, urlencode({'offset': offset - limit}))  # noqa
        resp.json(**kwargs)

    def on_get_versions(self, req, resp, *args, **kwargs):
        instance = self.get_object(**kwargs)
        route_id = kwargs.get('route_id')
        if route_id:
            version = instance.load_version(route_id)
            if not version:
                raise falcon.HTTPNotFound()
            resp.json(**version.as_resource)
        else:
            self.collection(req, resp, instance.versions.as_resource())


class Position(BaseCRUD):
    model = models.Position


class Housenumber(BaseCRUD):
    identifiers = ['cia']
    model = models.HouseNumber

    def on_get_positions(self, *args, **kwargs):
        instance = self.get_object(**kwargs)
        return self.collection(instance.position_set.as_resource)


class Locality(BaseCRUD):
    model = models.Locality
    identifiers = ['fantoir']

    def on_get_housenumbers(self, *args, **kwargs):
        instance = self.get_object(**kwargs)
        return self.collection(instance.housenumber_set.as_resource)


class Street(Locality):
    model = models.Street
    identifiers = ['fantoir']


class Municipality(BaseCRUD):
    identifiers = ['siren', 'insee']
    model = models.Municipality

    def on_get_streets(self, req, resp, *args, **kwargs):
        instance = self.get_object(**kwargs)
        self.collection(req, resp, instance.street_set.as_resource())

    def on_get_localities(self, req, resp, *args, **kwargs):
        instance = self.get_object(**kwargs)
        self.collection(req, resp, instance.locality_set.as_resource())