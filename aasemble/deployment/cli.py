import argparse
import json
import logging
import sys

from multiprocessing.pool import ThreadPool

import aasemble.client as client
from aasemble.deployment import loader
from aasemble.deployment.cloudconfigparser import load_cloud_config

DEFAULT_THREADS = 10

LOG = logging.getLogger(__name__)


def extract_substitutions(substargs):
    d = {}
    for arg in substargs:
        if '=' in arg:
            k, v = arg.split('=', 1)
            d[k] = v
    return d


def format_collection(collection):
    out = 'Nodes:\n'
    for node in collection.nodes:
        out += '  %s: %s\n' % (node.name, node.private.public_ips)
    return out


def handle_cluster_opts(options, substitutions):
    if options.new_cluster:
        cluster = client.AasembleClient().clusters.create().url
        substitutions['cluster'] = cluster
    elif options.cluster:
        cluster = options.cluster
        substitutions['cluster'] = cluster
    else:
        cluster = None
    return cluster


def apply(options):
    substitutions = extract_substitutions(options.substitutions)

    cluster = handle_cluster_opts(options, substitutions)
    LOG.info('Cluster ID: %s', cluster)

    resources = loader.load(options.stack, substitutions)
    cloud_driver_class, cloud_driver_kwargs, mappings = load_cloud_config(options.cloud)
    pool = ThreadPool(options.threads)
    cloud_driver = cloud_driver_class(mappings=mappings,
                                      pool=pool,
                                      namespace=options.namespace,
                                      cluster=cluster,
                                      **cloud_driver_kwargs)

    if not options.assume_empty:
        current_resources = cloud_driver.detect_resources()
        resources = resources - current_resources

    cloud_driver.apply_resources(resources)
    print(format_collection(resources))


def detect(options):
    cloud_driver_class, cloud_driver_kwargs, mappings = load_cloud_config(options.cloud)
    pool = ThreadPool(options.threads)
    cloud_driver = cloud_driver_class(mappings=mappings,
                                      pool=pool,
                                      namespace=options.namespace,
                                      **cloud_driver_kwargs)

    resources = cloud_driver.detect_resources()

    if getattr(options, 'json', False):
        print(json.dumps(resources.as_dict()))
    else:
        print(format_collection(resources))

    return cloud_driver, resources


def clean(options):
    cloud_driver, resources = detect(options)
    cloud_driver.clean_resources(resources)


def main(args=sys.argv[1:]):
    parser = argparse.ArgumentParser()

    parser.add_argument('--threads', type=int, default=DEFAULT_THREADS,
                        help='Number of threads [default={}]'.format(DEFAULT_THREADS))

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)-15s %(message)s')

    subparsers = parser.add_subparsers(help='Subcommand help', dest='subcmd')
    subparsers.required = True
    apply_parser = subparsers.add_parser('apply', help='Apply (launch/update) stack')
    apply_parser.set_defaults(func=apply)
    apply_parser.add_argument('--assume-empty', action='store_true', help='Ignore current resources')
    apply_parser.add_argument('--namespace', help='Namespace for resources')

    cluster_group = apply_parser.add_mutually_exclusive_group()
    cluster_group.add_argument('--new-cluster', action='store_true', help='Create new cluster')
    cluster_group.add_argument('--cluster', help='Use existing cluster')

    apply_parser.add_argument('stack', help='Stack description (yaml format)')
    apply_parser.add_argument('cloud', help='Cloud config')
    apply_parser.add_argument('substitutions', nargs='*', help='Substitutions (e.g. "foo=bar")', metavar='SUBST')

    detect_parser = subparsers.add_parser('detect', help='Detect current resources')
    detect_parser.set_defaults(func=detect)
    detect_parser.add_argument('cloud', help='Cloud config')
    detect_parser.add_argument('--namespace', help='Namespace for resources')
    detect_parser.add_argument('--json', action='store_true', help='Output as JSON')

    clean_parser = subparsers.add_parser('clean', help='Clean current resources')
    clean_parser.set_defaults(func=clean)
    clean_parser.add_argument('cloud', help='Cloud config')
    clean_parser.add_argument('--namespace', help='Namespace for resources')

    options = parser.parse_args(args)
    options.func(options)


if __name__ == '__main__':
    main()  # pragma: no cover
