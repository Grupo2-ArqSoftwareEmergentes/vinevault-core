from typing import Optional
from app.inventory_intelligence.domain.models.analysis_type import AnalysisType
from app.inventory_intelligence.interfaces.acl import WineCellarIntelligenceData


class PromptBuilder:
    @staticmethod
    def build_prompt(
        analysis_type: AnalysisType,
        cellar_data: WineCellarIntelligenceData,
        user_query: Optional[str] = None,
    ) -> str:
        # Prompt del Sistema principal
        system_instructions = (
            "Eres el Sommelier Inteligente de VineVault, un sistema experto en gestión de bodegas de vino IoT. "
            "Tu objetivo es dar recomendaciones profesionales, concisas y prácticas. "
            "Usa un tono profesional, claro y amigable.\n\n"
        )

        # Resumen estructurado de datos mínimos de la bodega (Optimizado para Tokens)
        data_summary = f"Bodega: {cellar_data.name} (Espacio: {cellar_data.space_name})\n"
        if cellar_data.description:
            data_summary += f"Descripción: {cellar_data.description}\n"

        # Inventario en formato compacto
        data_summary += "\nInventario actual:\n"
        if not cellar_data.inventory:
            data_summary += "- (Sin botellas registradas)\n"
        else:
            for item in cellar_data.inventory:
                data_summary += f"- {item.wine_name} | Tipo: {item.wine_type} | Edad: {item.age_years} años | Cantidad: {item.quantity} botellas\n"

        # Datos mínimos del dispositivo
        if cellar_data.device:
            d = cellar_data.device
            data_summary += f"\nSensor IoT vinculado: {d.serial_number}\nEstado: {d.status}\n"
            if d.last_seen_at:
                data_summary += f"Último reporte: {d.last_seen_at}\n"
            if d.configuration:
                data_summary += "Configuración de Alertas:\n"
                for k, v in d.configuration.items():
                    data_summary += f"  {k}: {v}\n"
        else:
            data_summary += "\nSensor IoT: Ninguno vinculado actualmente.\n"

        # Prompts específicos según el tipo de análisis
        if analysis_type == AnalysisType.STOCK_ANALYSIS:
            specific_prompt = (
                "Analiza el inventario anterior y responde las siguientes preguntas de manera estructurada:\n"
                "1. ¿Qué vinos/etiquetas de este inventario tienen mayor prioridad para vender/consumir primero y por qué (basado en edad u optimización de espacio)?\n"
                "2. ¿Qué vinos representan capital inmovilizado debido a alta cantidad acumulada sin variedad?\n"
                "3. Propón una sugerencia rápida de promoción o rotación para el administrador."
            )
        elif analysis_type == AnalysisType.PURCHASE_RECOMMENDATION:
            specific_prompt = (
                "Analiza el inventario actual y proporciona una recomendación de compras inteligente:\n"
                "1. ¿Qué tipos o etiquetas específicas de vino tienen riesgo de desabastecimiento (bajas cantidades o faltantes para una cava balanceada)?\n"
                "2. Recomienda una cantidad de botellas a comprar para cada uno.\n"
                "3. Mantén la recomendación acotada y realista para una cava de colección regular."
            )
        elif analysis_type == AnalysisType.MONTHLY_REPORT:
            specific_prompt = (
                "Genera un reporte mensual ejecutivo para esta cava de vinos de manera estructurada:\n"
                "1. Resumen general de la composición de la cava (porcentaje aproximado de tintos, blancos, etc. según los datos provistos).\n"
                "2. Estado del sensor IoT (anomalías de conectividad si el estado es inusual).\n"
                "3. Tres conclusiones o recomendaciones clave de conservación."
            )
        elif analysis_type == AnalysisType.SENSOR_ANALYSIS:
            specific_prompt = (
                "Analiza el sensor IoT vinculado a la cava y su configuración:\n"
                "1. Evalúa si el estado actual es seguro para la conservación del vino.\n"
                "2. Si existen configuraciones de umbrales (temperatura/humedad), explica la importancia de mantener el vino dentro de estos límites.\n"
                "3. Sugiere acciones correctivas si el sensor reporta un estado inusual o desconexión."
            )
        elif analysis_type == AnalysisType.CHAT:
            query = user_query or "Analiza mi cava y dame tus comentarios generales."
            specific_prompt = (
                f"El usuario hace la siguiente consulta específica sobre su cava: \"{query}\"\n"
                "Responde su consulta basándote únicamente en la información real del inventario y sensores provistos."
            )
        else:
            specific_prompt = "Genera un análisis general de la cava de vino provista."

        return f"{system_instructions}DATOS DE LA CAVA:\n{data_summary}\nINSTRUCCIÓN DE ANÁLISIS:\n{specific_prompt}"
