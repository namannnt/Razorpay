"""
Payment Recovery Provider abstraction for ChurnGuard.

This module defines the interface for payment operations (Razorpay integration).
Implements both:
- MockProvider (for testing/development)
- RazorpayProvider (for production with real API calls)
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime
import os
import logging

logger = logging.getLogger(__name__)


class PaymentRecoveryProvider(ABC):
    """
    Abstract base class for payment recovery providers.
    
    This abstraction allows swapping between:
    - MockProvider (for testing/development)
    - RazorpayProvider (for production with real API calls)
    - Future providers (Stripe, etc.)
    """
    
    @abstractmethod
    def create_payment_link(
        self,
        amount: int,
        currency: str,
        customer_email: str,
        subscription_id: int,
        failure_event_id: int,
        customer_name: str,
        plan_name: str,
        description: str = None
    ) -> Dict[str, Any]:
        """
        Create a payment link for the customer.
        
        Returns dict with:
        - payment_link_id: str (e.g., "pl_xxxxx")
        - short_url: str (customer-facing URL)
        - status: str
        - is_simulated: bool
        """
        pass
    
    @abstractmethod
    def retry_payment(
        self,
        subscription_id: int,
        failure_event_id: int,
        amount: int,
        currency: str
    ) -> Dict[str, Any]:
        """
        Attempt to retry the failed payment.
        
        Returns dict with:
        - success: bool
        - payment_id: Optional[str]
        - status: str
        - is_simulated: bool
        """
        pass
    
    @abstractmethod
    def get_provider_status(self) -> Dict[str, Any]:
        """Check if the provider is configured and healthy."""
        pass


class MockPaymentProvider(PaymentRecoveryProvider):
    """
    Mock payment provider for testing and development.
    
    This provider simulates Razorpay operations without making real API calls.
    All operations are marked as simulated and return deterministic results.
    """
    
    def __init__(self):
        self.call_count = 0
        self.is_configured = True
    
    def create_payment_link(
        self,
        amount: int,
        currency: str,
        customer_email: str,
        subscription_id: int,
        failure_event_id: int,
        customer_name: str,
        plan_name: str,
        description: str = None
    ) -> Dict[str, Any]:
        """
        Simulate creating a payment link.
        
        Does NOT make any external API calls.
        """
        self.call_count += 1
        
        # Generate deterministic mock payment link ID
        mock_link_id = f"pl_mock_{subscription_id}_{failure_event_id}_{self.call_count}"
        
        return {
            "payment_link_id": mock_link_id,
            "short_url": f"https://razorpay.me/mock/{mock_link_id}",
            "status": "active",
            "amount": amount,
            "currency": currency,
            "customer_email": customer_email,
            "customer_name": customer_name,
            "description": description or f"Payment recovery for subscription {subscription_id}",
            "is_simulated": True,
            "created_at": datetime.utcnow().isoformat(),
            "provider": "mock"
        }
    
    def retry_payment(
        self,
        subscription_id: int,
        failure_event_id: int,
        amount: int,
        currency: str
    ) -> Dict[str, Any]:
        """
        Simulate retrying a payment.
        
        Does NOT attempt to charge the customer.
        Returns a simulated pending status since we don't have real card details.
        """
        self.call_count += 1
        
        # Deterministic simulation based on failure code patterns
        # In reality, this would call Razorpay's charge API
        return {
            "success": False,  # Always pending in mock mode
            "payment_id": f"pay_mock_{failure_event_id}_{self.call_count}",
            "status": "pending_simulation",
            "amount": amount,
            "currency": currency,
            "is_simulated": True,
            "message": "Mock retry: No actual charge attempted. Integrate RazorpayProvider for real payments.",
            "provider": "mock"
        }
    
    def get_provider_status(self) -> Dict[str, Any]:
        """Return mock provider status."""
        return {
            "configured": True,
            "provider": "mock",
            "is_simulated": True,
            "api_calls_made": self.call_count,
            "message": "Mock provider active - no real payments will be processed"
        }


class RazorpayProvider(PaymentRecoveryProvider):
    """
    Real Razorpay payment provider using the official Razorpay SDK.
    
    This provider makes actual API calls to Razorpay's test or live environment
    based on the configured credentials.
    """
    
    def __init__(self, key_id: str = None, key_secret: str = None):
        self.key_id = key_id or os.getenv("RAZORPAY_KEY_ID")
        self.key_secret = key_secret or os.getenv("RAZORPAY_KEY_SECRET")
        self._client = None
        self._validate_configuration()
    
    def _validate_configuration(self):
        """Validate that Razorpay credentials are configured."""
        if not self.key_id or not self.key_secret:
            raise ValueError(
                "Razorpay credentials not configured. "
                "Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET environment variables."
            )
        # Note: Client initialization deferred until first use
        # to avoid importing razorpay package when using MockProvider
    
    def _get_client(self):
        """Lazy-load Razorpay client."""
        if self._client is None:
            try:
                import razorpay
                self._client = razorpay.Client(auth=(self.key_id, self.key_secret))
            except ImportError:
                raise ImportError(
                    "razorpay package not installed. "
                    "Run: pip install razorpay"
                )
        return self._client
    
    def create_payment_link(
        self,
        amount: int,
        currency: str,
        customer_email: str,
        subscription_id: int,
        failure_event_id: int,
        customer_name: str,
        plan_name: str,
        description: str = None
    ) -> Dict[str, Any]:
        """
        Create a real Razorpay payment link.
        
        Uses Razorpay's Payment Links API to generate a shareable link
        that customers can use to complete their payment.
        """
        try:
            client = self._get_client()
            
            # Build payment link payload per Razorpay API spec
            payload = {
                "amount": amount,  # Already in paise
                "currency": currency,
                "description": description or f"Payment recovery for {plan_name} - {customer_name}",
                "customer": {
                    "name": customer_name,
                    "email": customer_email
                },
                "notify": {
                    "sms": False,
                    "email": True
                },
                "reminder_enable": True,
                "reference_id": f"churnguard_{failure_event_id}_{subscription_id}",
                "callback_url": None,  # Optional callback after payment
                "callback_method": "get"  # Default method
            }
            
            # Create payment link via Razorpay API
            link = client.payment_link.create(payload)
            
            logger.info(f"Created Razorpay payment link: {link['id']} for subscription {subscription_id}")
            
            return {
                "payment_link_id": link["id"],
                "short_url": link["short_url"],
                "status": link["status"],
                "amount": link["amount"],
                "currency": link["currency"],
                "customer_email": customer_email,
                "customer_name": customer_name,
                "description": payload["description"],
                "reference_id": payload["reference_id"],
                "is_simulated": False,
                "created_at": datetime.fromtimestamp(link.get("created_at", 0)).isoformat() if link.get("created_at") else datetime.utcnow().isoformat(),
                "provider": "razorpay"
            }
            
        except Exception as e:
            logger.error(f"Failed to create Razorpay payment link: {str(e)}")
            raise
    
    def retry_payment(
        self,
        subscription_id: int,
        failure_event_id: int,
        amount: int,
        currency: str
    ) -> Dict[str, Any]:
        """
        Retry payment via Razorpay.
        
        Note: This is a placeholder for future implementation.
        Actual retry logic would depend on how you store customer payment methods
        and whether you're using Razorpay's recurring payment features.
        """
        # For now, return a not-implemented response
        # Future implementation could use Razorpay's Subscriptions API or saved cards
        return {
            "success": False,
            "payment_id": None,
            "status": "not_implemented",
            "amount": amount,
            "currency": currency,
            "is_simulated": False,
            "message": "Automatic retry not yet implemented. Use payment links for customer-initiated retries.",
            "provider": "razorpay"
        }
    
    def get_provider_status(self) -> Dict[str, Any]:
        """Check Razorpay provider status."""
        return {
            "configured": bool(self.key_id and self.key_secret),
            "provider": "razorpay",
            "is_simulated": False,
            "key_id_prefix": self.key_id[:8] + "..." if self.key_id else None,
            "message": "Razorpay provider configured and ready"
        }


def get_provider(use_mock: bool = True) -> PaymentRecoveryProvider:
    """
    Factory function to get the appropriate payment provider.
    
    Args:
        use_mock: If True, return MockPaymentProvider. 
                  If False, attempt to return RazorpayProvider.
    
    Returns:
        PaymentRecoveryProvider instance
    """
    if use_mock:
        return MockPaymentProvider()
    
    # Try to create real provider, fall back to mock if not configured
    try:
        provider = RazorpayProvider()
        return provider
    except (ValueError, ImportError) as e:
        logger.warning(f"Could not initialize RazorpayProvider: {e}. Falling back to MockProvider.")
        return MockPaymentProvider()
