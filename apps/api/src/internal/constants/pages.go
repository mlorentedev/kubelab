package constants

// URLs and endpoints
var URLs = struct {
	SuccessPages struct {
		Subscription string
		Resource     string
		Unsubscribe  string
		Booking      string
	}
	ErrorPages struct {
		NotFound string
	}
}{
	SuccessPages: struct {
		Subscription string
		Resource     string
		Unsubscribe  string
		Booking      string
	}{
		Subscription: "/success/subscribe",
		Resource:     "/success/resource",
		Unsubscribe:  "/success/unsubscribe",
		Booking:      "/success/booking",
	},
	ErrorPages: struct {
		NotFound string
	}{
		NotFound: "/errors/404",
	},
}
