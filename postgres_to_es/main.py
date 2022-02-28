import fcntl
import json
import logging
import os
from datetime import datetime
from logging import config

from config import DEFAULT_DATE, CHUNK_SIZE
from config import LOG_CONFIG
from utils.elastic_db import ELFilm
from utils.postgres_db import PGFilmWork
from utils.state import State, RedisStorage

config.dictConfig(LOG_CONFIG)


def run_once(fh):
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        logging.error("скрипт уже запущен!!!")
        os._exit(0)


def loader_es(pg: PGFilmWork, table: dict, es: ELFilm):
    table_name = table['name']
    limit = CHUNK_SIZE
    state_table = {}
    state_table_raw = state.get_state(table_name)

    if state_table_raw:
        state_table = json.loads(state_table_raw)
    date_start = state_table.get('date', DEFAULT_DATE)
    offset_start = state_table.get('offset', 0)
    date_end = date_start

    for modified_ids in pg.chunk_read_table_id(table_name, date_start, limit,
                                               offset_start):
        date_end = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        offset_start += limit
        if table['func_film_id']:
            film_modified_ids = pg.get_film_id_in_table(table_name,
                                                        [item['id'] for item in
                                                         modified_ids])
        else:
            film_modified_ids = modified_ids
        film_result = pg.get_film_data(
            [item['id'] for item in film_modified_ids])
        film_serialize = pg.transform(film_result)

        es.set_bulk('movies', film_serialize.values())
        state.set_state(table['name'], json.dumps(
            {'offset': offset_start, 'date': date_start}))
    state.set_state(table['name'], json.dumps({'offset': 0, 'date': date_end}))


if __name__ == '__main__':
    fh = open(os.path.realpath(__file__), 'r')
    run_once(fh)
    state = State(RedisStorage())
    pg = PGFilmWork()
    es = ELFilm()

    tables_pg = [
        {'name': 'genre', 'func_film_id': True},
        {'name': 'person', 'func_film_id': True},
        {'name': 'film_work', 'func_film_id': None},

    ]

    for table in tables_pg:
        # да, оно с одной стороны избыточно, но могут быть ситуации когда это
        # поможет минимизировать пропуск изменяющихся данных
        logging.info('start load table {}'.format(table['name']))
        loader_es(pg, table, es)
        logging.info('stop load table {}'.format(table['name']))
