$headers = @{
    "Content-Type" = "application/json; charset=utf-8" # Especifica charset=utf-8 aquí
}

$bodyObject = @{
    "message" = "Hola, me gustaría iniciar una auditoría de sostenibilidad."
}
# ConvertTo-Json generalmente maneja bien los caracteres UTF-8.
# La clave es cómo Invoke-WebRequest envía esta cadena.
$bodyJsonString = $bodyObject | ConvertTo-Json

# Para depurar, verifica cómo se ve la cadena JSON (opcional)
# Write-Host "JSON Body String: $bodyJsonString"

try {
    Write-Host "Enviando solicitud a http://127.0.0.1:5000/chat..."
    $response = Invoke-WebRequest -Uri http://127.0.0.1:5000/chat -Method POST -Headers $headers -Body $bodyJsonString -UseBasicParsing
    
    # Si la solicitud es exitosa (código 2xx)
    Write-Output "Solicitud Exitosa!"
    Write-Output "StatusCode: $($response.StatusCode)"
    # Write-Output "Headers: $($response.Headers | Out-String)" # Puede ser muy largo
    Write-Output "Content (Respuesta del servidor): $($response.Content)"

} catch {
    # Esto se ejecuta si Invoke-WebRequest encuentra un error HTTP (como 4xx o 5xx)
    Write-Warning "Error durante Invoke-WebRequest:"
    
    # Acceder a los detalles de la respuesta de error
    if ($_.Exception.Response) {
        $errorResponse = $_.Exception.Response
        Write-Output "StatusCode: $($errorResponse.StatusCode.value__)"
        Write-Output "StatusDescription: $($errorResponse.StatusDescription)"
        
        # Leer el cuerpo de la respuesta de error
        $responseStream = $errorResponse.GetResponseStream()
        $streamReader = New-Object System.IO.StreamReader($responseStream)
        $errorBody = $streamReader.ReadToEnd()
        $streamReader.Close()
        $responseStream.Close()
        Write-Output "Error Body from Server: $errorBody"
    } else {
        Write-Output "No response object in exception. Error message: $($_.Exception.Message)"
    }
}