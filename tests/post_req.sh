#!/bin/bash
requ=$1
curl -H 'Content-Type: application/json; charset=utf-8' --data @post_req${requ}.json http://localhost:8081/github

