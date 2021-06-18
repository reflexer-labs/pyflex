#!/bin/bash

#TESTCHAIN="testchain-value-fixed-discount-governance-median-multisig-basic"
#TESTCHAIN="rai-testchain-value-fixed-discount-uniswap-multisig-basic"
declare -a TESTCHAINS=("rai-testchain-value-fixed-discount-uniswap-multisig-safe")

run_test () {
  export TESTCHAIN=$1
  TEST_FILE=$2
  # Pull the docker image
  docker pull reflexer/${TESTCHAIN}

  # Remove existing container if tests not gracefully stopped
  docker-compose -f config/${TESTCHAIN}.yml down

  # Start ganache
  docker-compose -f config/${TESTCHAIN}.yml up -d ganache

  # Start parity and wait to initialize
  docker-compose -f config/${TESTCHAIN}.yml up -d parity
  sleep 2

  #Run the tests
  pytest -s --cov=pyflex --cov-report=term --cov-append tests/${TEST_FILE}
  TEST_RESULT=$?

  # Cleanup
  docker-compose -f config/${TESTCHAIN}.yml down
  return $TEST_RESULT
}

# If passing a single config or test file, just run tests on one testchain
while getopts :c:f: option
do
case "${option}"
in
c) TESTCHAIN=${OPTARG};;
f) TEST_FILE=${OPTARG};;
esac
done

if [ ! -z ${TESTCHAIN} ];then
  echo "Testing file ${TEST_FILE} on testchain ${TESTCHAIN}"
  run_test $TESTCHAIN $TEST_FILE
  exit $?
fi


COMBINED_RESULT=0
for config in "${TESTCHAINS[@]}"
do
  run_test $config
  COMBINED_RESULT=$(($COMBINED_RESULT + $?))
done
 

exit $COMBINED_RESULT
