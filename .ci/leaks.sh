#!/bin/bash

if [ ! -z $TRAVIS_PULL_REQUEST ]; then
    REPO_SLUG="/${TRAVIS_REPO_SLUG}"
    echo "Building for slug ${TRAVIS_REPO_SLUG}, commit ${TRAVIS_COMMIT}"
    # Audit the current commit for secrets
    docker run --rm --name=gitleaks -v $PWD:$REPO_SLUG zricethezav/gitleaks -v --repo-path=$REPO_SLUG --commit=$TRAVIS_COMMIT
fi
