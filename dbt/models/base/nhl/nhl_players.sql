SELECT
  nhl_player_id AS id,
  full_name,
  game_team_name AS team_name,
  SUM(stats_assists) AS assists,
  SUM(stats_goals) AS goals,
  SUM(stats_assists) + SUM(stats_goals) as points
FROM {{ ref('player_game_stats') }}
GROUP BY id, full_name, team_name
