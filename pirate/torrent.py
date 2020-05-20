import re
import sys
import gzip
import pyperclip
import urllib.request as request
import urllib.parse as parse
import urllib.error
import os.path

import pirate.data
import json

from datetime import datetime
from io import BytesIO


def parse_category(printer, category):
    try:
        category = int(category)
    except ValueError:
        pass
    if category in pirate.data.categories.values():
        return category
    elif category in pirate.data.categories.keys():
        return pirate.data.categories[category]
    else:
        printer.print('Invalid category ignored', color='WARN')
        return 0


def parse_sort(printer, sort):
    try:
        sort = int(sort)
    except ValueError:
        pass
    if sort in pirate.data.sorts.values():
        return sort
    elif sort in pirate.data.sorts.keys():
        return pirate.data.sorts[sort]
    else:
        printer.print('Invalid sort ignored', color='WARN')
        return 99


def pretty_size(size):
    ranges = [('PiB', 1125899906842624),
              ('TiB', 1099511627776),
              ('GiB', 1073741824),
              ('MiB', 1048576),
              ('KiB', 1024)]
    for unit, value in ranges:
        if size >= value:
            return '{:.1f} {}'.format(size/value, unit)
    return str(size) + ' B'


def pretty_date(ts):
    date = datetime.fromtimestamp(int(ts))
    return date.strftime('%Y-%m-%d %H:%M')


def make_magnet(name, info_hash):
    return 'magnet:?xt=urn:btih:{}&dn={}'.format(
        info_hash, parse.quote(name, ''))


def remote(printer, category, sort, mode, terms, mirror):
    results = []

    # Catch the Ctrl-C exception and exit cleanly
    try:
        req = request.Request(
            '{}/q.php?q={}&cat={}'.format(
                mirror, ' '.join(terms), category),
            headers=pirate.data.default_headers)
        try:
            f = request.urlopen(req, timeout=pirate.data.default_timeout)
        except urllib.error.URLError as e:
            raise e

        if f.info().get('Content-Encoding') == 'gzip':
            f = gzip.GzipFile(fileobj=BytesIO(f.read()))
        for res in json.load(f):
            res['size'] = pretty_size(int(res['size']))
            res['magnet'] = make_magnet(res['name'], res['info_hash'])
            res['info_hash'] = int(res['info_hash'], 16)
            res['uploaded'] = pretty_date(res['added'])
            results.append(res)

        return results

    except KeyboardInterrupt:
        printer.print('\nCancelled.')
        sys.exit(0)


def find_api(mirror):
    # try common paths
    for path in ['', '/apip', '/api.php?url=']:
        req = request.Request(mirror + path + '/q.php?q=test&cat=0',
                              headers=pirate.data.default_headers)
        try:
            f = request.urlopen(req, timeout=pirate.data.default_timeout)
            if f.info().get_content_type() == 'application/json':
                return mirror + path
        except urllib.error.URLError:
            pass

    # extract api path from main.js
    req = request.Request(mirror + '/static/main.js',
                          headers=pirate.data.default_headers)
    try:
        f = request.urlopen(req, timeout=pirate.data.default_timeout)
        if f.info().get_content_type() == 'application/javascript':
            match = re.search("var server='([^']+)'", f.read().decode())
            return mirror + match.group(1)
    except urllib.error.URLError:
        raise IOError('API not found: no main.js')

    raise IOError('API not found')


def get_torrent(info_hash):
    url = 'http://itorrents.org/torrent/{:X}.torrent'
    req = request.Request(url.format(info_hash),
                          headers=pirate.data.default_headers)
    req.add_header('Accept-encoding', 'gzip')

    torrent = request.urlopen(req, timeout=pirate.data.default_timeout)
    if torrent.info().get('Content-Encoding') == 'gzip':
        torrent = gzip.GzipFile(fileobj=BytesIO(torrent.read()))

    return torrent.read()


def save_torrents(printer, chosen_links, results, folder):
    for link in chosen_links:
        result = results[link]
        torrent_name = result['name'].replace('/', '_').replace('\\', '_')
        file = os.path.join(folder, torrent_name + '.torrent')

        try:
            torrent = get_torrent(result['info_hash'])
        except urllib.error.HTTPError as e:
            printer.print('There is no cached file for this torrent :('
                          ' \nCode: {} - {}'.format(e.code, e.reason),
                          color='ERROR')
        else:
            open(file, 'wb').write(torrent)
            printer.print('Saved {:X} in {}'.format(result['info_hash'], file))


def save_magnets(printer, chosen_links, results, folder):
    for link in chosen_links:
        result = results[link]
        torrent_name = result['name'].replace('/', '_').replace('\\', '_')
        file = os.path.join(folder,  torrent_name + '.magnet')

        printer.print('Saved {:X} in {}'.format(result['info_hash'], file))
        with open(file, 'w') as f:
            f.write(result['magnet'] + '\n')


def copy_magnets(printer, chosen_links, results):
    clipboard_text = ''
    for link in chosen_links:
        result = results[link]
        clipboard_text += result['magnet'] + "\n"
        printer.print('Copying {:X} to clipboard'.format(result['info_hash']))

    pyperclip.copy(clipboard_text)
