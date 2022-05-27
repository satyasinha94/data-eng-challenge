WITH ranked_teams AS (
    SELECT
      team_name,
      full_name,
      points,
      RANK() OVER (PARTITION BY team_name ORDER BY points DESC) AS rank
    from {{ ref('nhl_players') }}
    WHERE
      points > 0
)
SELECT
  team_name,
  full_name,
  points
FROM
  ranked_teams
WHERE
  rank = 1
