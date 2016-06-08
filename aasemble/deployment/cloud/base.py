import logging
import os.path
import threading
from multiprocessing.pool import ThreadPool

from libcloud.compute.providers import get_driver

import aasemble.deployment.cloud.models as cloud_models

LOG = logging.getLogger(__name__)
THREADS = 10  # These are really, really lightweight


class CloudDriver(object):
    def __init__(self, namespace=None, mappings=None, pool=None):
        self.mappings = mappings or {}
        self.pool = pool or ThreadPool(THREADS)
        self.secgroups = {}
        self.namespace = namespace
        self.locals = threading.local()

    @property
    def connection(self):
        if not hasattr(self.locals, '_connection'):
            driver = get_driver(self.provider)
            driver_args, driver_kwargs = self._get_driver_args_and_kwargs()
            LOG.info('Connecting to {}'.format(self.name))
            self.locals._connection = driver(*driver_args, **driver_kwargs)

        return self.locals._connection

    def _is_node_relevant(self, node):
        return self.namespace is None or self.get_namespace(node) == self.namespace

    def detect_nodes(self):
        nodes = set()

        for node in self._get_relevant_nodes():
            aasemble_node = self._aasemble_node_from_provider_node(node)
            nodes.add(aasemble_node)
            LOG.info('Detected node: %s' % aasemble_node.name)

        return nodes

    def _get_relevant_nodes(self):
        for node in self.connection.list_nodes():
            if self._is_node_relevant(node):
                yield node

    def detect_resources(self):
        collection = cloud_models.Collection()

        LOG.info('Detecting nodes')
        for node in self.detect_nodes():
            collection.nodes.add(node)

        LOG.info('Detecting security groups and security group rules')

        security_groups, security_group_rules = self.detect_firewalls()

        for security_group in security_groups:
            collection.security_groups.add(security_group)

        for security_group_rule in security_group_rules:
            collection.security_group_rules.add(security_group_rule)

        collection.connect()

        return collection

    def apply_mappings(self, obj_type, name):
        return self.mappings.get(obj_type, {}).get(name, name)

    def apply_resources(self, collection):
        self.pool.map(self.create_security_group, collection.security_groups)
        self.pool.map(self.create_node, collection.nodes)
        self.pool.map(self.create_security_group_rule, collection.security_group_rules)

    def delete_node(self, node):
        self.connection.destroy_node(node.private)

    def clean_resources(self, collection):
        self.pool.map(self.delete_node, collection.nodes)

    def expand_path(self, path):
        return os.path.expanduser(path)