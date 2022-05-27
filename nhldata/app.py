"""
    This is the NHL crawler.

Scattered throughout are TODO tips on what to look for.

Assume this job isn't expanding in scope, but pretend it will be pushed into production to run
automomously.  So feel free to add anywhere (not hinted, this is where we see your though process..)
    * error handling where you see things going wrong.
    * messaging for monitoring or troubleshooting
    * anything else you think is necessary to have for restful nights
"""
import logging
from datetime import datetime
from dataclasses import dataclass
import boto3
import requests
import pandas as pd
from botocore.config import Config
from dateutil.parser import parse as dateparse
import os
import argparse

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger(__name__)


class NHLApi:
    SCHEMA_HOST = "https://statsapi.web.nhl.com/"
    VERSION_PREFIX = "api/v1"

    def __init__(self, base=None):
        self.base = base if base else f'{self.SCHEMA_HOST}/{self.VERSION_PREFIX}'

    def schedule(self, start_date: datetime, end_date: datetime) -> dict:
        """
        returns a dict tree structure that is like
            "dates": [
                {
                    " #.. meta info, one for each requested date ",
                    "games": [
                        { #.. game info },
                        ...
                    ]
                },
                ...
            ]
        """
        return self._get(self._url('schedule'),
                         {'startDate': start_date.strftime('%Y-%m-%d'), 'endDate': end_date.strftime('%Y-%m-%d')})

    def boxscore(self, game_id):
        """
        returns a dict tree structure that is like
           "teams": {
                "home": {
                    " #.. other meta ",
                    "players": {
                        $player_id: {
                            "person": {
                                "id": $int,
                                "fullName": $string,
                                #-- other info
                                "currentTeam": {
                                    "name": $string,
                                    #-- other info
                                },
                                "stats": {
                                    "skaterStats": {
                                        "assists": $int,
                                        "goals": $int,
                                        #-- other status
                                    }
                                    #-- ignore "goalieStats"
                                }
                            }
                        },
                        #...
                    }
                },
                "away": {
                    #... same as "home"
                }
            }

            See tests/resources/boxscore.json for a real example response
        """
        url = self._url(f'game/{game_id}/boxscore')
        return self._get(url)

    def _get(self, url, params=None):
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            logging.exception("NETWORK PROBLEM")
            raise SystemExit(1)
        except requests.exceptions.HTTPError:
            logging.exception("UNSUCCESSFUL STATUS CODE")
            raise SystemExit(1)
        except requests.exceptions.Timeout:
            logging.exception("REQUEST TIMED OUT")
            raise SystemExit(1)
        return response.json()

    def _url(self, path):
        return f'{self.base}/{path}'


@dataclass
class StorageKey:
    def __init__(self, game_id, game_date):
        self._gameId = game_id
        self._gameDate = game_date.strftime("%Y%m%d")

    def key(self):
        """ renders the s3 key for the given set of properties """
        return f'{self._gameDate}_{self._gameId}.csv'


class Storage:
    def __init__(self, dest_bucket, s3_client):
        self._s3_client = s3_client
        self.bucket = dest_bucket

    def store_game(self, key: StorageKey, game_data) -> bool:
        self._s3_client.put_object(Bucket=self.bucket, Key=key.key(), Body=game_data)
        return True


class Crawler:
    """
    This class is responsible for writing CSV files (partitioned by date and game id) with player stats to an s3 bucket.
    The crawl method loops over games in a certain date range, grabs all the player stats by looping through
    several layers of a nested dict, then writes the files to s3 with their s3 key being generated by the StorageKey
    class and the storage of the files being handled by the Storage class.
    """

    def __init__(self, api: NHLApi, storage: Storage):
        self.api = api
        self.storage = storage

    def crawl(self, start_date: datetime, end_date: datetime) -> None:
        logging.info(f"STARTING CRAWL")
        game_dates = self.api.schedule(start_date, end_date)["dates"]
        for date in game_dates:
            game_date = datetime.strptime(date["date"], '%Y-%m-%d')
            games_df = pd.DataFrame(pd.json_normalize(date.get("games")))
            player_columns = ["player_person_id",
                              "player_person_currentTeam_name",
                              "player_person_fullName",
                              "player_stats_skaterStats_assists",
                              "player_stats_skaterStats_goals",
                              "side"
                              ]
            player_stats_df = pd.DataFrame()
            for idx, row in games_df.iterrows():
                stats_dict = self.api.boxscore(row["gamePk"])
                for team_side in ('home', 'away'):
                    team_name = stats_dict["teams"][team_side]["team"]["name"]
                    players = stats_dict["teams"][team_side]["players"].keys()
                    for player in players:
                        if stats_dict["teams"][team_side]["players"][f"{player}"]["stats"].get(
                                "skaterStats") is not None:
                            skater_stats = stats_dict["teams"][team_side]["players"][f"{player}"]["stats"][
                                "skaterStats"]
                            player_name = stats_dict["teams"][team_side]["players"][f"{player}"]["person"]["fullName"]
                            goals, assists = [skater_stats[k] for k in ["goals", "assists"]]

                            player_stats = pd.Series(
                                [player.replace('ID', ''),
                                 team_name,
                                 player_name,
                                 assists,
                                 goals,
                                 team_side
                                 ],
                                index=player_columns)
                            player_stats_df = player_stats_df.append(player_stats, ignore_index=True)
                s3_key = StorageKey(row["gamePk"], game_date)
                self.storage.store_game(s3_key, player_stats_df[player_columns].to_csv(index=False))
                logging.info(f"WRITING FILE: {s3_key.key()} to s3_data/{self.storage.bucket}/{s3_key.key()}")
        logging.info(f"FILE WRITES COMPLETE")


def main():
    parser = argparse.ArgumentParser(description='NHL Stats crawler')
    parser.add_argument('--start-date', type=str, help="format: yyyy-mm-dd")
    parser.add_argument('--end-date', type=str, help="format: yyyy-mm-dd")
    args = vars(parser.parse_args())
    dest_bucket = os.environ.get('DEST_BUCKET', 'output')
    start_date = dateparse(args['start_date'])
    end_date = dateparse(args['end_date'])
    api = NHLApi()
    s3client = boto3.client('s3', config=Config(signature_version='s3v4'),
                            endpoint_url=os.environ.get('S3_ENDPOINT_URL'))
    storage = Storage(dest_bucket, s3client)
    crawler = Crawler(api, storage)
    crawler.crawl(start_date, end_date)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        logging.exception("ERROR EXECUTING JOB")
        raise SystemExit(1)
