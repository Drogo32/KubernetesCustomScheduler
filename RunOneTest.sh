#!/bin/bash

if [ $# -ne 3 ]; then
  echo "Wrong number of arguments provided!"
  echo "Usage: $0 [algorithm] [# of replicas] [pods to scale]"
  echo ""
  echo "PODS TO SCALE:"
  echo "frontend"
  echo "multiple"
  exit 1
fi

if ! [[ $2 =~ ^-?[0-9]+$ ]]; then
  echo "$2 is NOT a number."
  exit 1
fi

if [ "$3" != "frontend" ] && [ "$3" != "multiple" ]; then
  echo "Invalid argument: $3"
  echo "Valid options are: frontend, multiple"
  exit 1
fi


if [ "$1" == "least_allocated" ]; then
  if [ "$3" == "frontend" ]; then
    kubectl apply -f kubernetes-manifests-frontend.yaml
    sleep 2

    kubectl scale deployment frontend --replicas=1 -n boutique
  else
    kubectl apply -f kubernetes-manifests-multiple.yaml
    sleep 2

    kubectl scale deployment recommendationservice --replicas=1 -n boutique
    kubectl scale deployment frontend --replicas=1 -n boutique
    kubectl scale deployment paymentservice --replicas=1 -n boutique
    kubectl scale deployment productcatalogservice --replicas=1 -n boutique
    kubectl scale deployment cartservice --replicas=1 -n boutique
    kubectl scale deployment redis-cart --replicas=1 -n boutique
    kubectl scale deployment loadgenerator --replicas=1 -n boutique
    kubectl scale deployment currencyservice --replicas=1 -n boutique
    kubectl scale deployment shippingservice --replicas=1 -n boutique
    kubectl scale deployment adservice --replicas=1 -n boutique
  fi
  echo "Waiting for pods to scale... (60s)"
  sleep 60

  screen -dmS custom_scheduler bash -c "python custom_scheduler.py 3 ./outputs/"
  echo "Waiting for custom scheduler to spin up... (30s)"
  sleep 30

  if [ "$3" == "frontend" ]; then
    kubectl scale deployment frontend --replicas="$2" -n boutique
  else
    scaleto=$(( $2 / 10 ))
    kubectl scale deployment recommendationservice --replicas="$scaleto" -n boutique
    kubectl scale deployment frontend --replicas="$scaleto" -n boutique
    kubectl scale deployment paymentservice --replicas="$scaleto" -n boutique
    kubectl scale deployment productcatalogservice --replicas="$scaleto" -n boutique
    kubectl scale deployment cartservice --replicas="$scaleto" -n boutique
    kubectl scale deployment redis-cart --replicas="$scaleto" -n boutique
    kubectl scale deployment loadgenerator --replicas="$scaleto" -n boutique
    kubectl scale deployment currencyservice --replicas="$scaleto" -n boutique
    kubectl scale deployment shippingservice --replicas="$scaleto" -n boutique
    kubectl scale deployment adservice --replicas="$scaleto" -n boutique
  fi

elif [ "$1" == "requested_to_capacity_ratio" ]; then
  if [ "$3" == "frontend" ]; then
    kubectl apply -f kubernetes-manifests-frontend.yaml
    sleep 2

    kubectl scale deployment frontend --replicas=1 -n boutique
  else
    kubectl apply -f kubernetes-manifests-multiple.yaml
    sleep 2

    kubectl scale deployment recommendationservice --replicas=1 -n boutique
    kubectl scale deployment frontend --replicas=1 -n boutique
    kubectl scale deployment paymentservice --replicas=1 -n boutique
    kubectl scale deployment productcatalogservice --replicas=1 -n boutique
    kubectl scale deployment cartservice --replicas=1 -n boutique
    kubectl scale deployment redis-cart --replicas=1 -n boutique
    kubectl scale deployment loadgenerator --replicas=1 -n boutique
    kubectl scale deployment currencyservice --replicas=1 -n boutique
    kubectl scale deployment shippingservice --replicas=1 -n boutique
    kubectl scale deployment adservice --replicas=1 -n boutique
  fi
  echo "Waiting for pods to scale... (60s)"
  sleep 60

  screen -dmS custom_scheduler bash -c "python custom_scheduler.py 3 ./outputs/"
  echo "Waiting for custom scheduler to spin up... (30s)"
  sleep 30

  if [ "$3" == "frontend" ]; then
    kubectl scale deployment frontend --replicas=4 -n boutique
  else
    scaleto=$(( $2 / 10 ))
    kubectl scale deployment recommendationservice --replicas="$scaleto" -n boutique
    kubectl scale deployment frontend --replicas="$scaleto" -n boutique
    kubectl scale deployment paymentservice --replicas="$scaleto" -n boutique
    kubectl scale deployment productcatalogservice --replicas="$scaleto" -n boutique
    kubectl scale deployment cartservice --replicas="$scaleto" -n boutique
    kubectl scale deployment redis-cart --replicas="$scaleto" -n boutique
    kubectl scale deployment loadgenerator --replicas="$scaleto" -n boutique
    kubectl scale deployment currencyservice --replicas="$scaleto" -n boutique
    kubectl scale deployment shippingservice --replicas="$scaleto" -n boutique
    kubectl scale deployment adservice --replicas="$scaleto" -n boutique
  fi
elif [ "$1" == "dot_product_scoring" ]; then
  if [ "$3" == "frontend" ]; then
    kubectl apply -f kubernetes-manifests-frontend.yaml
    sleep 2

    kubectl scale deployment frontend --replicas=1 -n boutique
  else
    kubectl apply -f kubernetes-manifests-multiple.yaml
    sleep 2

    kubectl scale deployment recommendationservice --replicas=1 -n boutique
    kubectl scale deployment frontend --replicas=1 -n boutique
    kubectl scale deployment paymentservice --replicas=1 -n boutique
    kubectl scale deployment productcatalogservice --replicas=1 -n boutique
    kubectl scale deployment cartservice --replicas=1 -n boutique
    kubectl scale deployment redis-cart --replicas=1 -n boutique
    kubectl scale deployment loadgenerator --replicas=1 -n boutique
    kubectl scale deployment currencyservice --replicas=1 -n boutique
    kubectl scale deployment shippingservice --replicas=1 -n boutique
    kubectl scale deployment adservice --replicas=1 -n boutique
  fi
  echo "Waiting for pods to scale..."
  sleep 60

  screen -dmS custom_scheduler bash -c "python custom_scheduler.py 5 ./outputs/"
  sleep 30

  if [ "$3" == "frontend" ]; then
    kubectl scale deployment frontend --replicas="$2" -n boutique
  else
    scaleto=$(( $2 / 10 ))
    kubectl scale deployment recommendationservice --replicas="$scaleto" -n boutique
    kubectl scale deployment frontend --replicas="$scaleto" -n boutique
    kubectl scale deployment paymentservice --replicas="$scaleto" -n boutique
    kubectl scale deployment productcatalogservice --replicas="$scaleto" -n boutique
    kubectl scale deployment cartservice --replicas="$scaleto" -n boutique
    kubectl scale deployment redis-cart --replicas="$scaleto" -n boutique
    kubectl scale deployment loadgenerator --replicas="$scaleto" -n boutique
    kubectl scale deployment currencyservice --replicas="$scaleto" -n boutique
    kubectl scale deployment shippingservice --replicas="$scaleto" -n boutique
    kubectl scale deployment adservice --replicas="$scaleto" -n boutique
  fi
elif [ "$1" == "lp_relaxation" ]; then
  if [ "$3" == "frontend" ]; then
    kubectl apply -f kubernetes-manifests-frontend.yaml
    sleep 2

    kubectl scale deployment frontend --replicas=1 -n boutique
  else
    kubectl apply -f kubernetes-manifests-multiple.yaml
    sleep 2

    kubectl scale deployment recommendationservice --replicas=1 -n boutique
    kubectl scale deployment frontend --replicas=1 -n boutique
    kubectl scale deployment paymentservice --replicas=1 -n boutique
    kubectl scale deployment productcatalogservice --replicas=1 -n boutique
    kubectl scale deployment cartservice --replicas=1 -n boutique
    kubectl scale deployment redis-cart --replicas=1 -n boutique
    kubectl scale deployment loadgenerator --replicas=1 -n boutique
    kubectl scale deployment currencyservice --replicas=1 -n boutique
    kubectl scale deployment shippingservice --replicas=1 -n boutique
    kubectl scale deployment adservice --replicas=1 -n boutique
  fi
  echo "Waiting for pods to scale..."
  sleep 60

  screen -dmS custom_scheduler bash -c "python custom_scheduler.py 1 ./outputs/"
  sleep 30

  if [ "$3" == "frontend" ]; then
    kubectl scale deployment frontend --replicas="$2" -n boutique
  else
    scaleto=$(( $2 / 10 ))
    kubectl scale deployment recommendationservice --replicas="$scaleto" -n boutique
    kubectl scale deployment frontend --replicas="$scaleto" -n boutique
    kubectl scale deployment paymentservice --replicas="$scaleto" -n boutique
    kubectl scale deployment productcatalogservice --replicas="$scaleto" -n boutique
    kubectl scale deployment cartservice --replicas="$scaleto" -n boutique
    kubectl scale deployment redis-cart --replicas="$scaleto" -n boutique
    kubectl scale deployment loadgenerator --replicas="$scaleto" -n boutique
    kubectl scale deployment currencyservice --replicas="$scaleto" -n boutique
    kubectl scale deployment shippingservice --replicas="$scaleto" -n boutique
    kubectl scale deployment adservice --replicas="$scaleto" -n boutique
  fi
elif [ "$1" == "fairness_relaxation" ]; then
  if [ "$3" == "frontend" ]; then
    kubectl apply -f kubernetes-manifests-frontend.yaml
    sleep 2

    kubectl scale deployment frontend --replicas=1 -n boutique
  else
    kubectl apply -f kubernetes-manifests-multiple.yaml
    sleep 2

    kubectl scale deployment recommendationservice --replicas=1 -n boutique
    kubectl scale deployment frontend --replicas=1 -n boutique
    kubectl scale deployment paymentservice --replicas=1 -n boutique
    kubectl scale deployment productcatalogservice --replicas=1 -n boutique
    kubectl scale deployment cartservice --replicas=1 -n boutique
    kubectl scale deployment redis-cart --replicas=1 -n boutique
    kubectl scale deployment loadgenerator --replicas=1 -n boutique
    kubectl scale deployment currencyservice --replicas=1 -n boutique
    kubectl scale deployment shippingservice --replicas=1 -n boutique
    kubectl scale deployment adservice --replicas=1 -n boutique
  fi
  echo "Waiting for pods to scale..."
  sleep 60

  screen -dmS custom_scheduler bash -c "python custom_scheduler.py 2 ./outputs/"
  sleep 30

  if [ "$3" == "frontend" ]; then
    kubectl scale deployment frontend --replicas="$2" -n boutique
  else
    scaleto=$(( $2 / 10 ))
    kubectl scale deployment recommendationservice --replicas="$scaleto" -n boutique
    kubectl scale deployment frontend --replicas="$scaleto" -n boutique
    kubectl scale deployment paymentservice --replicas="$scaleto" -n boutique
    kubectl scale deployment productcatalogservice --replicas="$scaleto" -n boutique
    kubectl scale deployment cartservice --replicas="$scaleto" -n boutique
    kubectl scale deployment redis-cart --replicas="$scaleto" -n boutique
    kubectl scale deployment loadgenerator --replicas="$scaleto" -n boutique
    kubectl scale deployment currencyservice --replicas="$scaleto" -n boutique
    kubectl scale deployment shippingservice --replicas="$scaleto" -n boutique
    kubectl scale deployment adservice --replicas="$scaleto" -n boutique
  fi
else
  echo "Invalid argument: $1"
  echo "Valid options are:"
  echo "least_allocated"
  echo "requested_to_capacity_ratio"
  echo "dot_product_scoring"
  echo "lp_relaxation"
  echo "fairness_relaxation"
  exit 1
fi


echo "Waiting for scheduler to complete... This may take a few minutes."

while screen -ls | grep -q "custom_scheduler"; do
  sleep 2
done
