"""Synthetic coverage for local Phish discovery and statistics."""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from local_data_mcp.audit import AuditWriter
from local_data_mcp.phish_importer import SCHEMA
from local_data_mcp.service import LookupService


class PhishStatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "phish.sqlite"
        self.audit = self.root / "audit.jsonl"
        with closing(sqlite3.connect(self.db)) as c, c:
            c.executescript(SCHEMA)
            c.execute("INSERT INTO phish_sync_runs(id, started_at_utc, finished_at_utc, status, api_base) VALUES(1,'start','finish','succeeded','test')")
            c.executemany("""INSERT INTO phish_shows(id,show_date,venue_id,venue_name,city,state,country,last_synced_run_id)
                VALUES(?,?,?,?,?,?,?,1)""", [
                (1, '1999-01-01', 10, 'Old', 'Madison', 'WI', 'USA'),
                (2, '1999-02-01', 10, 'New % Hall', 'Madison', 'WI', 'USA'),
                (3, '2000-01-01', 11, 'Alpha', 'Chicago', 'IL', 'USA'),
                (4, '2000-02-01', None, None, None, None, None)])
            c.executemany("INSERT INTO phish_tracks(id,show_id,title,position,last_synced_run_id) VALUES(?,?,?,1,1)",
                          [(1,1,'one'),(2,2,'two'),(3,3,'three'),(4,4,'unlinked')])
            c.executemany("INSERT INTO phish_songs(id,title,last_synced_run_id) VALUES(?,?,1)", [(1,'Beta'),(2,'Alpha')])
            c.executemany("INSERT INTO phish_track_songs(track_id,song_id,association_order) VALUES(?,?,?)",
                          [(1,1,0),(1,1,1),(1,2,2),(2,1,0),(3,2,0)])
        self.service = LookupService(self.root / 'mock.sqlite', AuditWriter(self.audit), self.db, require_question_id=True)
        question = self.service.invoke('audit_record_question', {'question': 'Discover Phish data'})
        self.qid = question['_audit']['request_id']

    def call(self, tool, **kwargs):
        return self.service.invoke(tool, {'question_id': self.qid, **kwargs})

    def test_years_and_snapshot_pages(self):
        first = self.call('phish_list_years', limit=1)
        self.assertEqual([{'year':'1999', 'show_count':2}], first['data']['years'])
        self.assertEqual(2, first['data']['total'])
        self.assertTrue(first['data']['has_more'])
        self.assertEqual('finish', first['data']['catalog_synced_at'])
        second = self.call('phish_list_years', limit=1, offset=1, expected_sync_id=1)
        self.assertEqual('2000', second['data']['years'][0]['year'])
        self.assertEqual('invalid_input', self.call('phish_list_years', offset=1)['error']['code'])
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("INSERT INTO phish_sync_runs(id,started_at_utc,finished_at_utc,status,api_base) VALUES(2,'a','b','succeeded','test')")
        self.assertEqual('snapshot_changed', self.call('phish_list_years', offset=1, expected_sync_id=1)['error']['code'])
        self.assertEqual(2, self.call('phish_list_years')['data']['catalog_sync_id'])

    def test_venues_group_latest_and_literal_search(self):
        result = self.call('phish_list_venues', query='%', state='wi', country='usa')['data']
        self.assertEqual(1, result['total'])
        self.assertEqual('New % Hall', result['venues'][0]['venue_name'])
        self.assertEqual(2, result['venues'][0]['show_count'])
        self.assertEqual(1, result['unidentified_venue_show_count'])
        self.assertEqual(0, self.call('phish_list_venues', query='_')['data']['total'])
        self.assertEqual([11,10], [x['venue_id'] for x in self.call('phish_list_venues')['data']['venues']])

    def test_song_distinct_medley_filters_and_coverage(self):
        data = self.call('phish_song_frequency')['data']
        self.assertEqual([('Alpha',2),('Beta',2)], [(x['title'],x['track_count']) for x in data['songs']])
        self.assertEqual(1, data['unassociated_track_count'])
        self.assertIn('not the official', data['metric_definition'])
        data = self.call('phish_song_frequency', year=1999, venue_id=10, limit=1)['data']
        self.assertEqual(('Beta',2), (data['songs'][0]['title'],data['songs'][0]['track_count']))
        self.assertTrue(data['has_more'])
        self.assertEqual(0, self.call('phish_song_frequency', year=2001)['data']['total'])
        self.assertEqual('invalid_input', self.call('phish_song_frequency', year=True)['error']['code'])

    def test_missing_incompatible_empty_and_input(self):
        self.service.phish_database_path = self.root / 'missing'
        self.assertEqual('catalog_unavailable', self.call('phish_list_years')['error']['code'])
        self.service.phish_database_path = self.db
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("UPDATE phish_sync_runs SET status='failed'")
        self.assertEqual('catalog_unavailable', self.call('phish_list_years')['error']['code'])
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("UPDATE phish_sync_runs SET status='succeeded'")
            c.execute("DELETE FROM phish_track_songs")
            c.execute("DELETE FROM phish_tracks")
            c.execute("DELETE FROM phish_shows")
        self.assertEqual([], self.call('phish_list_years')['data']['years'])
        self.assertEqual('invalid_input', self.call('phish_list_years', limit=51)['error']['code'])
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('DROP TABLE phish_shows')
        self.assertEqual('catalog_unavailable', self.call('phish_list_years')['error']['code'])

    def test_audits_and_write_failure(self):
        for tool in ('phish_list_years', 'phish_list_venues', 'phish_song_frequency'):
            result = self.call(tool, limit=1)
            event = json.loads(self.audit.read_text(encoding='utf-8').splitlines()[-1])
            self.assertEqual(self.qid, event['arguments']['question_id'])
            self.assertEqual(result['data'], event['result']['data'])
            self.assertEqual('invalid_input', self.service.invoke(tool, {})['error']['code'])
        result = self.call('phish_list_years', offset=1)
        event = json.loads(self.audit.read_text(encoding='utf-8').splitlines()[-1])
        self.assertEqual(result['error'], event['result']['error'])
        self.service.audit.write = lambda event: (_ for _ in ()).throw(PermissionError('denied'))
        self.assertEqual('audit_failure', self.call('phish_song_frequency')['error']['code'])

    def test_mcp_integration(self):
        from mcp.shared.memory import create_connected_server_and_client_session
        from local_data_mcp.server import create_server

        async def run():
            server = create_server(self.root / 'mock.sqlite', self.audit, self.db)
            async with create_connected_server_and_client_session(server) as session:
                def payload(result):
                    return result.structuredContent or json.loads(result.content[0].text)
                names = {tool.name for tool in (await session.list_tools()).tools}
                self.assertTrue({'phish_list_years','phish_list_venues','phish_song_frequency'} <= names)
                question = payload(await session.call_tool('audit_record_question', {'question':'List years'}))
                qid = question['_audit']['request_id']
                for name in ('phish_list_years','phish_list_venues','phish_song_frequency'):
                    result = payload(await session.call_tool(name, {'question_id':qid}))
                    self.assertTrue(result['ok'])
                    event = payload(await session.call_tool('audit_get_event', {'request_id':result['_audit']['request_id'], 'question_id':qid}))
                    self.assertEqual(qid, event['data']['event']['arguments']['question_id'])
        asyncio.run(run())

    def test_mcp_stdio(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def run():
            env = dict(os.environ)
            env.update(LOCAL_DATA_MCP_DB_PATH=str(self.root / 'mock.sqlite'),
                       LOCAL_DATA_MCP_PHISH_DB_PATH=str(self.db), LOCAL_DATA_MCP_AUDIT_PATH=str(self.audit))
            params = StdioServerParameters(command=sys.executable, args=['-m', 'local_data_mcp.server'], env=env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    def payload(result):
                        return result.structuredContent or json.loads(result.content[0].text)
                    question = payload(await session.call_tool('audit_record_question', {'question':'Which years have shows?'}))
                    result = payload(await session.call_tool('phish_list_years', {'question_id':question['_audit']['request_id']}))
                    self.assertEqual(['1999', '2000'], [row['year'] for row in result['data']['years']])
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
