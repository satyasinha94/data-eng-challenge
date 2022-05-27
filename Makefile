
.PHONY: init test step1 step2 catalog_data run_sql dbt_run dbt_test

BACKSLASH = '\\'

init:
	pip install -r requirements.txt
	pip install -r test-requirements.txt

test:
	pytest -vv

clean:
	rm -rf s3_data && mkdir s3_data

mkbucket:
	mkdir -p s3_data/data-bucket && touch s3_data/data-bucket/.gitkeep

down:
	docker-compose down

step1: down clean mkbucket
	docker-compose up --build
#--- part two
catalog_data:
			  touch s3_data/load_data.sql
			  rm s3_data/load_data.sql
			  @for f in $(shell ls s3_data/data-bucket); \
			  do echo $(BACKSLASH)copy game_stats from s3_data/data-bucket/$${f} \
			  WITH \(FORMAT csv, HEADER\) >> s3_data/load_data.sql; done


run_sql: catalog_data
	docker exec \
	  -w /data \
	  $$(basename $(PWD))_db_1 \
	  psql -h db -U postgres -f s3_data/load_data.sql

dbt_run:
	docker run --rm \
	  --network host \
	  -v $(PWD)/dbt:/usr/app \
	  -v $(PWD)/.dbt:/root/.dbt \
	  fishtownanalytics/dbt:0.17.2 run

dbt_test:
	docker run --rm \
	  --network host \
	  -v $(PWD)/dbt:/usr/app \
	  -v $(PWD)/.dbt:/root/.dbt \
	  fishtownanalytics/dbt:0.17.2 test

step2: run_sql dbt_run dbt_test

points_leaders:
	docker run --rm  \
	  --network host \
	  -e PGPASSWORD=password \
	  --entrypoint psql \
	  postgres:12-alpine \
	  -h localhost -U postgres -c "select * from points_leaders order by points DESC LIMIT 10;"
	

