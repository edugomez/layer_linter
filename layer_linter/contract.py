import yaml
import os
import logging
from copy import copy

from .dependencies import ImportPath


logger = logging.getLogger(__name__)


class ContractParseError(IOError):
    pass


class Layer:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name

    def __repr__(self):
        return '<{}: {}>'.format(self.__class__.__name__, self)


class Contract:
    def __init__(self, name, packages, layers, whitelisted_paths=None, recursive=False):
        self.name = name
        self.packages = packages
        self.layers = layers
        self.whitelisted_paths = whitelisted_paths if whitelisted_paths else []
        self.recursive = recursive

    def check_dependencies(self, dependencies):
        self.illegal_dependencies = []

        logger.debug('Checking dependencies for contract {}...'.format(self))

        for package in self.packages:
            for layer in reversed(self.layers):
                self._check_layer_does_not_import_downstream(layer, package, dependencies)

    def _check_layer_does_not_import_downstream(self, layer, package, dependencies):

        logger.debug("Layer '{}' in package '{}'.".format(layer, package))

        modules_in_this_layer = self._get_modules_in_layer(layer, package, dependencies)
        modules_in_downstream_layers = self._get_modules_in_downstream_layers(
            layer, package, dependencies)
        logger.debug('Modules in this layer: {}'.format(modules_in_this_layer))
        logger.debug('Modules in downstream layer: {}'.format(modules_in_downstream_layers))

        for upstream_module in modules_in_this_layer:
            for downstream_module in modules_in_downstream_layers:
                logger.debug('Upstream {}, downstream {}.'.format(upstream_module,
                                                                  downstream_module))
                path = dependencies.find_path(
                    upstream=downstream_module,
                    downstream=upstream_module,
                    ignore_paths=self.whitelisted_paths,
                )
                logger.debug('Path is {}.'.format(path))
                if path and not self._path_is_via_another_layer(path, layer, package):
                    logger.debug('Illegal dependency found: {}'.format(path))
                    self._update_illegal_dependencies(path)

    def _get_modules_in_layer(self, layer, package, dependencies):
        """
        Args:
            layer: The Layer object.
            package: absolute name of the package containing the layer (string).
            dependencies: the DependencyGraph object.
        Returns:
            List of modules names within that layer, including the layer module itself.
            Includes grandchildren and deeper.
        """
        layer_module = "{}.{}".format(package, layer.name)
        modules = [layer_module]
        modules.extend(
            dependencies.get_descendants(layer_module)
        )
        return modules

    def _get_modules_in_downstream_layers(self, layer, package, dependencies):
        modules = []
        for downstream_layer in self._get_layers_downstream_of(layer):
            modules.extend(
                # self._get_modules_in_layer(downstream_layer, package, dependencies)
                ["{}.{}".format(package, downstream_layer.name)]
            )
        return modules

    def _path_is_via_another_layer(self, path, current_layer, package):
        other_layers = list(copy(self.layers))
        other_layers.remove(current_layer)

        layer_modules = ['{}.{}'.format(package, layer.name) for layer in other_layers]
        modules_via = path[1:-1]

        return any(path_module in layer_modules for path_module in modules_via)

    def _update_illegal_dependencies(self, path):
        # Don't duplicate path. So if the path is already present in another dependency,
        # don't add it. If another dependency is present in this path, replace it with this one.
        new_path_set = set(path)
        logger.debug('Updating illegal dependencies with {}.'.format(path))
        illegal_dependencies_copy = self.illegal_dependencies[:]
        paths_to_remove = []
        add_path = True
        for existing_path in illegal_dependencies_copy:
            existing_path_set = set(existing_path)
            logger.debug('Comparing new path with {}...'.format(existing_path))
            if new_path_set.issubset(existing_path_set):
                # Remove the existing_path, as the new path will be more succinct.
                logger.debug('Removing existing.')
                paths_to_remove.append(existing_path)
                add_path = True
            elif existing_path_set.issubset(new_path_set):
                # Don't add the new path, it's implied more succinctly with the existing path.
                logger.debug('Skipping new path.')
                add_path = False

        logger.debug('Paths to remove: {}'.format(paths_to_remove))
        self.illegal_dependencies = [
            i for i in self.illegal_dependencies if i not in paths_to_remove
        ]
        if add_path:
            self.illegal_dependencies.append(path)

    @property
    def is_kept(self):
        try:
            return len(self.illegal_dependencies) == 0
        except AttributeError:
            raise RuntimeError(
                'Cannot check whether contract is kept '
                'until check_dependencies is called.'
            )

    def _get_layers_downstream_of(self, layer):
        return reversed(self.layers[:self.layers.index(layer)])

    def __str__(self):
        return self.name

    def __repr__(self):
        return '<{}: {}>'.format(self.__class__.__name__, self)


def contract_from_yaml(key, data):
    layers = []
    for layer_data in data['layers']:
        layers.append(Layer(layer_data))

    whitelisted_paths = []
    for whitelist_data in data.get('whitelisted_paths', []):
        try:
            importer, imported = whitelist_data.split(' <- ')
        except ValueError:
            raise ValueError('Whitelisted paths must be in the format '
                             '"importer.module <- imported.module".')

        whitelisted_paths.append(ImportPath(importer, imported))

    return Contract(
        name=key,
        packages=data['packages'],
        layers=layers,
        whitelisted_paths=whitelisted_paths,
    )


def get_contracts(path):
    """Given a path to a project, read in any contracts from a layers.yml file.
    Args:
        path (string): the path to the project root.
    Returns:
        A list of Contract instances.
    """
    contracts = []

    file_path = os.path.join(path, 'layers.yml')

    with open(file_path, 'r') as file:
        try:
            data_from_yaml = yaml.load(file)
        except Exception as e:
            logger.debug(e)
            raise ContractParseError('Could not parse {}.'.format(file_path))
        for key, data in data_from_yaml.items():
            contracts.append(contract_from_yaml(key, data))

    return contracts
