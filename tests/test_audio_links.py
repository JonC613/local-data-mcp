import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from local_data_mcp.audit import AuditWriter
from local_data_mcp.service import LookupService


class AudioLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = self.root / "phish.sqlite"
        self.audit = self.root / "audit.jsonl"
        with closing(sqlite3.connect(self.catalog)) as c, c:
            c.executescript("""
              CREATE TABLE phish_shows(id INTEGER PRIMARY KEY,show_date TEXT,venue_name TEXT,city TEXT,state TEXT,country TEXT,audio_status TEXT);
              CREATE TABLE phish_tracks(id INTEGER PRIMARY KEY,show_id INTEGER,slug TEXT,title TEXT,set_name TEXT,position INTEGER,audio_status TEXT);
              CREATE TABLE phish_songs(id INTEGER PRIMARY KEY,title TEXT);
              CREATE TABLE phish_track_songs(track_id INTEGER,song_id INTEGER,association_order INTEGER);
            """)
            c.executemany("INSERT INTO phish_shows VALUES(?,?,?,?,?,?,?)", [
                (1,"2000-09-24","Target","Minneapolis","MN","USA","complete"),
                (2,"2001-01-01","Venue","City","WI","USA","none")])
            c.executemany("INSERT INTO phish_tracks VALUES(?,?,?,?,?,?,?)", [
                (1,1,"cities","Cities","Set 2",1,"complete"),
                (2,1,"medley","TMWSIY > Avenu","Set 1",2,"complete"),
                (3,2,None,"Cities","Set 1",1,"none"),
                (4,2,"../unsafe","Cities","Set 1",2,"none")])
            c.executemany("INSERT INTO phish_songs VALUES(?,?)", [(1,"Cities"),(2,"Avenu Malkenu")])
            c.executemany("INSERT INTO phish_track_songs VALUES(?,?,?)", [(1,1,0),(2,2,0),(2,2,1),(3,1,0)])
        self.service = LookupService(self.root / "mock.sqlite", AuditWriter(self.audit), self.catalog, require_question_id=True)
        self.qid = self.service.invoke("audit_record_question", {"question":"Audio links?"})["_audit"]["request_id"]

    def call(self, name, **args):
        return self.service.invoke(name, {"question_id":self.qid,**args})

    def test_show_page_and_not_found(self):
        data=self.call("phish_get_show_audio", show_date="2000-09-24")["data"]
        self.assertEqual("https://phish.in/2000-09-24", data["shows"][0]["url"])
        self.assertEqual("complete", data["shows"][0]["audio_status"])
        self.assertEqual("not_found",self.call("phish_get_show_audio",show_date="1998-01-01")["error"]["code"])
        self.assertEqual("invalid_input",self.call("phish_get_show_audio",show_date="not-a-date")["error"]["code"])

    def test_tracks_medley_slug_and_pagination(self):
        first=self.call("phish_find_song_audio",query="Cities",limit=1)["data"]
        self.assertEqual(3, first["total"])
        self.assertTrue(first["has_more"])
        self.assertEqual("https://phish.in/2000-09-24/cities",first["tracks"][0]["url"])
        later=self.call("phish_find_song_audio",query="Cities",limit=2,offset=1)["data"]
        self.assertEqual([None,None],[x["url"] for x in later["tracks"]])
        self.assertEqual("none",later["tracks"][0]["audio_status"])
        medley=self.call("phish_find_song_audio",query="Avenu Malkenu",show_date="2000-09-24")["data"]
        self.assertEqual(1,medley["total"])
        self.assertEqual("https://phish.in/2000-09-24/medley",medley["tracks"][0]["url"])
        self.assertEqual(0,self.call("phish_find_song_audio",query="%")["data"]["total"])
        self.assertEqual("invalid_input",self.call("phish_find_song_audio",query="Cities",limit=51)["error"]["code"])

    def test_audit_and_fail_closed(self):
        result=self.call("phish_find_song_audio",query="Cities",show_date="2000-09-24")
        event=json.loads(self.audit.read_text().splitlines()[-1])
        self.assertEqual(self.qid,event["arguments"]["question_id"])
        self.assertEqual(result["data"],event["result"]["data"])
        self.assertEqual("invalid_input",self.service.invoke("phish_get_show_audio",{"show_date":"2000-09-24"})["error"]["code"])
        self.service.audit.write=lambda event: (_ for _ in ()).throw(PermissionError("denied"))
        self.assertEqual("audit_failure",self.call("phish_get_show_audio",show_date="2000-09-24")["error"]["code"])

    def test_mcp_discovery_and_calls(self):
        from local_data_mcp.server import create_server
        from mcp.shared.memory import create_connected_server_and_client_session
        async def run():
            server=create_server(self.root/"mock",self.audit,self.catalog)
            async with create_connected_server_and_client_session(server) as session:
                def payload(r):return r.structuredContent or json.loads(r.content[0].text)
                self.assertTrue({"phish_get_show_audio","phish_find_song_audio"} <= {t.name for t in (await session.list_tools()).tools})
                q=payload(await session.call_tool("audit_record_question",{"question":"Listen to Cities"}))
                r=payload(await session.call_tool("phish_find_song_audio",{"query":"Cities","show_date":"2000-09-24","question_id":q["_audit"]["request_id"]}))
                self.assertEqual("https://phish.in/2000-09-24/cities",r["data"]["tracks"][0]["url"])
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()