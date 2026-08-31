# ============================================================================
# Makefile — AI Customer Support Agent (Bedrock AgentCore)
# Reproduce y documenta todos los comandos de despliegue del proyecto.
# Todas las recetas corren vía PowerShell para consistencia con el resto
# de la guía. Usa '>' como prefijo de receta (no tabs) — ver .RECIPEPREFIX.
# ============================================================================
.RECIPEPREFIX := >
SHELL := powershell.exe
.SHELLFLAGS := -NoProfile -Command

REGION      := us-east-1
ROLE_NAME   := csai-lambda-exec-role

.PHONY: help account iam-role lambda-package lambda-deploy lambda-update lambda-test clean-artifacts

help:
> Write-Host "Targets disponibles: account, iam-role, lambda-package, lambda-deploy, lambda-update, lambda-test, clean-artifacts"

## Muestra el Account ID actual (util para copiar/pegar ARNs)
account:
> aws sts get-caller-identity --query "Account" --output text

## Fase 1.1 - Crear el rol de ejecucion IAM para los Lambdas
iam-role:
> aws iam create-role --role-name $(ROLE_NAME) --assume-role-policy-document file://lambda/trust-policy.json
> aws iam attach-role-policy --role-name $(ROLE_NAME) --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

## Fase 1.2 - Empaquetar los Lambdas en ZIP
lambda-package:
> Compress-Archive -Path .\lambda\order_tracker.py -DestinationPath .\lambda\order_tracker.zip -Force
> Compress-Archive -Path .\lambda\refund_processor.py -DestinationPath .\lambda\refund_processor.zip -Force

## Fase 1.2 - Crear las funciones Lambda (primera vez)
lambda-deploy: lambda-package
> aws lambda create-function --function-name order-tracker --runtime python3.13 --role arn:aws:iam::376582749663:role/$(ROLE_NAME) --handler order_tracker.lambda_handler --zip-file fileb://lambda/order_tracker.zip --timeout 10 --memory-size 128
> aws lambda create-function --function-name refund-processor --runtime python3.13 --role arn:aws:iam::376582749663:role/$(ROLE_NAME) --handler refund_processor.lambda_handler --zip-file fileb://lambda/refund_processor.zip --timeout 10 --memory-size 128

## Actualizar codigo de los Lambdas ya existentes (tras editarlos)
lambda-update: lambda-package
> aws lambda update-function-code --function-name order-tracker --zip-file fileb://lambda/order_tracker.zip
> aws lambda update-function-code --function-name refund-processor --zip-file fileb://lambda/refund_processor.zip

## Prueba rapida de invocacion directa del order-tracker
lambda-test:
> aws lambda invoke --function-name order-tracker --cli-binary-format raw-in-base64-out --payload '{\"resource\":\"/orders/{order_id}\",\"httpMethod\":\"GET\",\"pathParameters\":{\"order_id\":\"ORD-001\"}}' response.json
> Get-Content response.json

## Limpieza de artefactos locales (zips, respuestas de prueba)
clean-artifacts:
> Remove-Item .\lambda\*.zip, .\response.json -ErrorAction SilentlyContinue