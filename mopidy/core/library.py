from __future__ import absolute_import, unicode_literals

import collections
import logging
import operator
import urlparse

from mopidy.utils import deprecation, validation


logger = logging.getLogger(__name__)


class LibraryController(object):
    pykka_traversable = True

    def __init__(self, backends, core):
        self.backends = backends
        self.core = core

    def _get_backend(self, uri):
        uri_scheme = urlparse.urlparse(uri).scheme
        return self.backends.with_library.get(uri_scheme, None)

    def _get_backends_to_uris(self, uris):
        if uris:
            backends_to_uris = collections.defaultdict(list)
            for uri in uris:
                backend = self._get_backend(uri)
                if backend is not None:
                    backends_to_uris[backend].append(uri)
        else:
            backends_to_uris = dict([
                (b, None) for b in self.backends.with_library.values()])
        return backends_to_uris

    def browse(self, uri):
        """
        Browse directories and tracks at the given ``uri``.

        ``uri`` is a string which represents some directory belonging to a
        backend. To get the intial root directories for backends pass
        :class:`None` as the URI.

        Returns a list of :class:`mopidy.models.Ref` objects for the
        directories and tracks at the given ``uri``.

        The :class:`~mopidy.models.Ref` objects representing tracks keep the
        track's original URI. A matching pair of objects can look like this::

            Track(uri='dummy:/foo.mp3', name='foo', artists=..., album=...)
            Ref.track(uri='dummy:/foo.mp3', name='foo')

        The :class:`~mopidy.models.Ref` objects representing directories have
        backend specific URIs. These are opaque values, so no one but the
        backend that created them should try and derive any meaning from them.
        The only valid exception to this is checking the scheme, as it is used
        to route browse requests to the correct backend.

        For example, the dummy library's ``/bar`` directory could be returned
        like this::

            Ref.directory(uri='dummy:directory:/bar', name='bar')

        :param string uri: URI to browse
        :rtype: list of :class:`mopidy.models.Ref`

        .. versionadded:: 0.18
        """
        if uri is None:
            return self._roots()
        elif not uri.strip():
            return []
        validation.check_uri(uri)
        return self._browse(uri)

    def _roots(self):
        directories = set()
        backends = self.backends.with_library_browse.values()
        futures = {b: b.library.root_directory for b in backends}
        for backend, future in futures.items():
            try:
                directories.add(future.get())
            except Exception:
                logger.exception('%s backend caused an exception.',
                                 backend.actor_ref.actor_class.__name__)
        return sorted(directories, key=operator.attrgetter('name'))

    def _browse(self, uri):
        scheme = urlparse.urlparse(uri).scheme
        backend = self.backends.with_library_browse.get(scheme)
        try:
            if backend:
                return backend.library.browse(uri).get()
        except Exception:
            logger.exception('%s backend caused an exception.',
                             backend.actor_ref.actor_class.__name__)
        return []

    def get_distinct(self, field, query=None):
        """
        List distinct values for a given field from the library.

        This has mainly been added to support the list commands the MPD
        protocol supports in a more sane fashion. Other frontends are not
        recommended to use this method.

        :param string field: One of ``artist``, ``albumartist``, ``album``,
            ``composer``, ``performer``, ``date``or ``genre``.
        :param dict query: Query to use for limiting results, see
            :meth:`search` for details about the query format.
        :rtype: set of values corresponding to the requested field type.

        .. versionadded:: 1.0
        """
        validation.check_choice(field, validation.DISTINCT_FIELDS)
        query is None or validation.check_query(query)  # TODO: normalize?

        result = set()
        futures = {b: b.library.get_distinct(field, query)
                   for b in self.backends.with_library.values()}
        for backend, future in futures.items():
            try:
                result.update(future.get())
            except Exception:
                logger.exception('%s backend caused an exception.',
                                 backend.actor_ref.actor_class.__name__)
        return result

    def get_images(self, uris):
        """Lookup the images for the given URIs

        Backends can use this to return image URIs for any URI they know about
        be it tracks, albums, playlists... The lookup result is a dictionary
        mapping the provided URIs to lists of images.

        Unknown URIs or URIs the corresponding backend couldn't find anything
        for will simply return an empty list for that URI.

        :param uris: list of URIs to find images for
        :type uris: list of string
        :rtype: {uri: tuple of :class:`mopidy.models.Image`}

        .. versionadded:: 1.0
        """
        validation.check_uris(uris)

        futures = {
            backend: backend.library.get_images(backend_uris)
            for (backend, backend_uris)
            in self._get_backends_to_uris(uris).items() if backend_uris}

        results = {uri: tuple() for uri in uris}
        for backend, future in futures.items():
            try:
                for uri, images in future.get().items():
                    results[uri] += tuple(images)
            except Exception:
                logger.exception('%s backend caused an exception.',
                                 backend.actor_ref.actor_class.__name__)
        return results

    def find_exact(self, query=None, uris=None, **kwargs):
        """Search the library for tracks where ``field`` is ``values``.

        .. deprecated:: 1.0
            Use :meth:`search` with ``exact`` set.
        """
        deprecation.warn('core.library.find_exact')
        return self.search(query=query, uris=uris, exact=True, **kwargs)

    def lookup(self, uri=None, uris=None):
        """
        Lookup the given URIs.

        If the URI expands to multiple tracks, the returned list will contain
        them all.

        :param uri: track URI
        :type uri: string or :class:`None`
        :param uris: track URIs
        :type uris: list of string or :class:`None`
        :rtype: list of :class:`mopidy.models.Track` if uri was set or
            {uri: list of :class:`mopidy.models.Track`} if uris was set.

        .. versionadded:: 1.0
            The ``uris`` argument.

        .. deprecated:: 1.0
            The ``uri`` argument. Use ``uris`` instead.
        """
        none_set = uri is None and uris is None
        both_set = uri is not None and uris is not None

        if none_set or both_set:
            raise ValueError("One of 'uri' or 'uris' must be set")

        # TODO: validation.one_of(*args)?

        uris is None or validation.check_uris(uris)
        uri is None or validation.check_uri(uri)

        if uri:
            deprecation.warn('core.library.lookup:uri_arg')

        if uri is not None:
            uris = [uri]

        futures = {}
        result = {u: [] for u in uris}

        # TODO: lookup(uris) to backend APIs
        for backend, backend_uris in self._get_backends_to_uris(uris).items():
            for u in backend_uris:
                futures[(backend, u)] = backend.library.lookup(u)

        for (backend, u), future in futures.items():
            try:
                result[u] = future.get()
            except Exception:
                logger.exception('%s backend caused an exception.',
                                 backend.actor_ref.actor_class.__name__)

        if uri:
            return result[uri]
        return result

    def refresh(self, uri=None):
        """
        Refresh library. Limit to URI and below if an URI is given.

        :param uri: directory or track URI
        :type uri: string
        """
        uri is None or validation.check_uri(uri)

        futures = {}
        backends = {}
        uri_scheme = urlparse.urlparse(uri).scheme if uri else None

        for backend_scheme, backend in self.backends.with_playlists.items():
            backends.setdefault(backend, set()).add(backend_scheme)

        for backend, backend_schemes in backends.items():
            if uri_scheme is None or uri_scheme in backend_schemes:
                futures[backend] = backend.library.refresh(uri)

        for backend, future in futures.items():
            try:
                future.get()
            except Exception:
                logger.exception('%s backend caused an exception.',
                                 backend.actor_ref.actor_class.__name__)

    def search(self, query=None, uris=None, exact=False, **kwargs):
        """
        Search the library for tracks where ``field`` contains ``values``.

        If ``uris`` is given, the search is limited to results from within the
        URI roots. For example passing ``uris=['file:']`` will limit the search
        to the local backend.

        Examples::

            # Returns results matching 'a' in any backend
            search({'any': ['a']})

            # Returns results matching artist 'xyz' in any backend
            search({'artist': ['xyz']})

            # Returns results matching 'a' and 'b' and artist 'xyz' in any
            # backend
            search({'any': ['a', 'b'], 'artist': ['xyz']})

            # Returns results matching 'a' if within the given URI roots
            # "file:///media/music" and "spotify:"
            search({'any': ['a']}, uris=['file:///media/music', 'spotify:'])

            # Returns results matching artist 'xyz' and 'abc' in any backend
            search({'artist': ['xyz', 'abc']})

        :param query: one or more queries to search for
        :type query: dict
        :param uris: zero or more URI roots to limit the search to
        :type uris: list of string or :class:`None`
        :param exact: if the search should use exact matching
        :type exact: :class:`bool`
        :rtype: list of :class:`mopidy.models.SearchResult`

        .. versionadded:: 1.0
            The ``exact`` keyword argument, which replaces :meth:`find_exact`.

        .. deprecated:: 1.0
            Previously, if the query was empty, and the backend could support
            it, all available tracks were returned. This has not changed, but
            it is strongly discouraged. No new code should rely on this
            behavior.

        .. deprecated:: 1.1
            Providing the search query via ``kwargs`` is no longer supported.
        """
        query = _normalize_query(query or kwargs)

        uris is None or validation.check_uris(uris)
        query is None or validation.check_query(query)
        validation.check_boolean(exact)

        if kwargs:
            deprecation.warn('core.library.search:kwargs_query')

        if not query:
            deprecation.warn('core.library.search:empty_query')

        futures = {}
        for backend, backend_uris in self._get_backends_to_uris(uris).items():
            futures[backend] = backend.library.search(
                query=query, uris=backend_uris, exact=exact)

        results = []
        for backend, future in futures.items():
            try:
                results.append(future.get())
            except TypeError:
                backend_name = backend.actor_ref.actor_class.__name__
                logger.warning(
                    '%s does not implement library.search() with "exact" '
                    'support. Please upgrade it.', backend_name)
            except LookupError:
                # Some of our tests check for this to catch bad queries. This
                # is silly and should be replaced with query validation before
                # passing it to the backends.
                raise
            except Exception:
                logger.exception('%s backend caused an exception.',
                                 backend.actor_ref.actor_class.__name__)

        return [r for r in results if r]


def _normalize_query(query):
    broken_client = False
    # TODO: this breaks if query is not a dictionary like object...
    for (field, values) in query.items():
        if isinstance(values, basestring):
            broken_client = True
            query[field] = [values]
    if broken_client:
        logger.warning(
            'A client or frontend made a broken library search. Values in '
            'queries must be lists of strings, not a string. Please check what'
            ' sent this query and file a bug. Query: %s', query)
    if not query:
        logger.warning(
            'A client or frontend made a library search with an empty query. '
            'This is strongly discouraged. Please check what sent this query '
            'and file a bug.')
    return query
