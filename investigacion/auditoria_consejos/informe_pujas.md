# Pujas del cuaderno de mercado

Esto no es la puja del optimizador. Esa cifra, la reserva y la probabilidad del plan no se guardaron. Aquí están las 39 filas «PUJAR» de `market_decision_snapshots` que traen un importe, del 22 de octubre al 14 de noviembre.

El precio de quien ganó solo está cuando el cuaderno marcó la fila como ganada o perdida (`paid_eur`). Una compra anterior no entra, y dos fotos de la misma subasta cuentan una vez (1 foto de más). Así quedan 3 subastas. Otras 35 recomendaciones no tienen precio de cierre: nadie las compró en la ventana, o el desenlace sigue abierto. Cero de las 39 acabaron en «hit».

En esas 3, la cifra sugerida cubre o iguala lo que pagó el ganador en 2 (67%). Intervalo de Wilson al 95 %: 21%–94%. El intervalo es tan ancho que no se puede decir que la recomendación se quede corta de forma sistemática, ni lo contrario.

Mediana de (cifra − precio pagado): 0.00 M€. Se quedan por debajo 1 veces; en ese caso el hueco mediano es −1.03 M€.

Cubrir el precio pagado no significa que la puja se hubiera ganado: «lost» quiere decir que la compró otro equipo, no que la cifra fuera insuficiente. La segunda oferta no está. La API manda el recuento de pujas y no los importes, así que el sobreprecio frente a la segunda no se puede medir.
